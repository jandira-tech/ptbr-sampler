#!/usr/bin/env python3
"""Repository-root compatibility re-export for :func:`ptbr_sampler.sample`.

Prefer ``from ptbr_sampler import TimePeriod, sample`` in installed-wheel code;
this module remains at the repository root for backward compatibility with
in-checkout scripts and notebooks.
"""

from ptbr_sampler import TimePeriod, sample

__all__ = ['TimePeriod', 'sample']
