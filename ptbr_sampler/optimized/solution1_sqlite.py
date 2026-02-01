"""
Solution 1: SQLite with Pre-calculated Cumulative Weights
==========================================================

This solution uses SQLite to store demographic data with pre-calculated cumulative
weight distributions for O(log n) weighted sampling using binary search.

Performance: ~50-100x faster than JSON for large datasets
Memory: Low (disk-based with minimal RAM usage)
Setup time: One-time conversion from JSON to SQLite
"""

import json
import random
import sqlite3
from pathlib import Path
from typing import Optional, Tuple
from loguru import logger


class SQLiteLocationSampler:
    """Optimized location sampler using SQLite with cumulative weight distribution."""

    def __init__(self, db_path: str | Path):
        """Initialize the sampler with SQLite database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._ensure_indexes()

    @classmethod
    def from_json(cls, json_path: str | Path, db_path: str | Path):
        """Create SQLite database from JSON file with cumulative weights.

        Args:
            json_path: Path to source JSON file
            db_path: Path to destination SQLite database

        Returns:
            Initialized SQLiteLocationSampler instance
        """
        db_path = Path(db_path)

        # Remove existing database
        if db_path.exists():
            db_path.unlink()

        logger.info(f"Converting {json_path} to SQLite database...")

        # Load JSON data
        with Path(json_path).open(encoding='utf-8') as f:
            data = json.load(f)

        # Create connection
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Create states table with cumulative weights
        cursor.execute('''
            CREATE TABLE states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                state_name TEXT NOT NULL,
                state_abbr TEXT NOT NULL,
                population_percentage REAL NOT NULL,
                cumulative_weight REAL NOT NULL,
                UNIQUE(state_name)
            )
        ''')

        # Create cities table with cumulative weights per state
        cursor.execute('''
            CREATE TABLE cities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                city_name TEXT NOT NULL,
                city_uf TEXT NOT NULL,
                uf_code TEXT,
                city_code TEXT,
                city_population INTEGER,
                population_percentage_total REAL,
                population_percentage_state REAL NOT NULL,
                cumulative_weight_state REAL NOT NULL,
                ddd TEXT,
                cep_range_begins TEXT,
                cep_range_ends TEXT,
                ceps_json TEXT,
                UNIQUE(city_name, city_uf)
            )
        ''')

        # Insert states with cumulative weights
        logger.info("Inserting states with cumulative weights...")
        states_list = sorted(data['states'].items())
        cumulative = 0.0
        total_state_weight = sum(s['population_percentage'] for _, s in states_list)

        for state_name, state_data in states_list:
            weight = state_data['population_percentage'] / total_state_weight
            cumulative += weight
            cursor.execute('''
                INSERT INTO states (state_name, state_abbr, population_percentage, cumulative_weight)
                VALUES (?, ?, ?, ?)
            ''', (state_name, state_data['state_abbr'], weight, cumulative))

        # Insert cities with cumulative weights per state
        logger.info("Inserting cities with cumulative weights per state...")

        # Group cities by state and calculate cumulative weights
        cities_by_state = {}
        for city_id, city_data in data['cities'].items():
            state_uf = city_data['city_uf']
            if state_uf not in cities_by_state:
                cities_by_state[state_uf] = []

            # Extract city_name
            city_name = city_data.get('city_name', city_id.split('_')[0] if '_' in city_id else city_id)
            cities_by_state[state_uf].append((city_name, city_data))

        # Process each state's cities
        for state_uf, cities in cities_by_state.items():
            # Sort for deterministic ordering
            cities.sort(key=lambda x: x[0])

            # Calculate cumulative weights
            total_city_weight = sum(c[1]['population_percentage_state'] for c in cities)
            cumulative = 0.0

            for city_name, city_data in cities:
                weight = city_data['population_percentage_state'] / total_city_weight if total_city_weight > 0 else 0
                cumulative += weight

                # Serialize CEPs as JSON string
                ceps_json = json.dumps(city_data.get('ceps', []))

                cursor.execute('''
                    INSERT INTO cities (
                        city_name, city_uf, uf_code, city_code, city_population,
                        population_percentage_total, population_percentage_state,
                        cumulative_weight_state, ddd, cep_range_begins, cep_range_ends, ceps_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    city_name,
                    city_data['city_uf'],
                    city_data.get('uf_code'),
                    city_data.get('city_code'),
                    city_data.get('city_population'),
                    city_data.get('population_percentage_total'),
                    weight,
                    cumulative,
                    city_data.get('ddd'),
                    city_data.get('cep_range_begins'),
                    city_data.get('cep_range_ends'),
                    ceps_json
                ))

        conn.commit()

        # Create indexes
        logger.info("Creating indexes...")
        cursor.execute('CREATE INDEX idx_states_cumulative ON states(cumulative_weight)')
        cursor.execute('CREATE INDEX idx_cities_state_cumulative ON cities(city_uf, cumulative_weight_state)')
        cursor.execute('CREATE INDEX idx_cities_lookup ON cities(city_name, city_uf)')

        conn.commit()
        conn.close()

        logger.info(f"SQLite database created successfully: {db_path}")
        return cls(db_path)

    def _ensure_indexes(self):
        """Ensure all required indexes exist."""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT name FROM sqlite_master WHERE type='index' AND name='idx_states_cumulative'
        ''')
        if not cursor.fetchone():
            logger.warning("Missing indexes, creating them...")
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_states_cumulative ON states(cumulative_weight)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_cities_state_cumulative ON cities(city_uf, cumulative_weight_state)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_cities_lookup ON cities(city_name, city_uf)')
            self.conn.commit()

    def get_state(self) -> Tuple[str, str]:
        """Get a random state weighted by population using binary search.

        Returns:
            Tuple of (state_name, state_abbreviation)
        """
        rand = random.random()
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT state_name, state_abbr
            FROM states
            WHERE cumulative_weight >= ?
            ORDER BY cumulative_weight
            LIMIT 1
        ''', (rand,))

        result = cursor.fetchone()
        if result:
            return result['state_name'], result['state_abbr']

        # Fallback to last state if rounding issues
        cursor.execute('SELECT state_name, state_abbr FROM states ORDER BY cumulative_weight DESC LIMIT 1')
        result = cursor.fetchone()
        return result['state_name'], result['state_abbr']

    def get_city(self, state_abbr: Optional[str] = None) -> Tuple[str, str]:
        """Get a random city weighted by population using binary search.

        Args:
            state_abbr: Optional state abbreviation to filter cities

        Returns:
            Tuple of (city_name, state_abbreviation)
        """
        if state_abbr is None:
            _, state_abbr = self.get_state()

        rand = random.random()
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT city_name, city_uf
            FROM cities
            WHERE city_uf = ? AND cumulative_weight_state >= ?
            ORDER BY cumulative_weight_state
            LIMIT 1
        ''', (state_abbr, rand))

        result = cursor.fetchone()
        if result:
            return result['city_name'], result['city_uf']

        # Fallback to last city in state if rounding issues
        cursor.execute('''
            SELECT city_name, city_uf FROM cities
            WHERE city_uf = ?
            ORDER BY cumulative_weight_state DESC LIMIT 1
        ''', (state_abbr,))
        result = cursor.fetchone()
        return result['city_name'], result['city_uf']

    def get_state_and_city(self) -> Tuple[str, str, str]:
        """Get a random state and city combination.

        Returns:
            Tuple of (state_name, state_abbreviation, city_name)
        """
        state_name, state_abbr = self.get_state()
        city_name, _ = self.get_city(state_abbr)
        return state_name, state_abbr, city_name

    def get_city_data(self, city_name: str, state_abbr: str) -> dict:
        """Get complete city data.

        Args:
            city_name: Name of the city
            state_abbr: State abbreviation

        Returns:
            Dictionary with city data
        """
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM cities WHERE city_name = ? AND city_uf = ?
        ''', (city_name, state_abbr))

        result = cursor.fetchone()
        if result:
            data = dict(result)
            # Parse CEPs JSON
            data['ceps'] = json.loads(data.get('ceps_json', '[]'))
            return data
        return {}

    def get_random_cep(self, city_name: str, state_abbr: str) -> str:
        """Get a random CEP for a city.

        Args:
            city_name: Name of the city
            state_abbr: State abbreviation

        Returns:
            Random CEP string
        """
        city_data = self.get_city_data(city_name, state_abbr)

        if city_data.get('ceps'):
            return random.choice(city_data['ceps'])

        # Generate from range if available
        if city_data.get('cep_range_begins') and city_data.get('cep_range_ends'):
            range_start = int(city_data['cep_range_begins'].replace('-', ''))
            range_end = int(city_data['cep_range_ends'].replace('-', ''))
            return str(random.randint(range_start, range_end))

        return "00000000"

    def close(self):
        """Close database connection."""
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Example usage and conversion utility
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python solution1_sqlite.py <json_path> <db_path>")
        print("Example: python solution1_sqlite.py data/cities_with_ceps.json data/cities_optimized.db")
        sys.exit(1)

    json_path = sys.argv[1]
    db_path = sys.argv[2]

    # Convert JSON to SQLite
    sampler = SQLiteLocationSampler.from_json(json_path, db_path)

    # Test sampling
    print("\nTesting sampling (10 samples):")
    for i in range(10):
        state_name, state_abbr, city_name = sampler.get_state_and_city()
        print(f"{i+1}. {city_name}, {state_name} ({state_abbr})")

    sampler.close()
    print(f"\nDatabase created successfully: {db_path}")
