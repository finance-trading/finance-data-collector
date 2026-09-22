# finance-data-collector
Finance Data Collector

## Local SEC Data

SEC filing packages are centralized under `sec/<company>/`. The directory is
local-only and excluded from Git because the filing archive is several
gigabytes. Research projects read this canonical store directly and do not keep
local `company/<company>/sec` directories.

The SEC download skill writes new ticker data to `sec/<TICKER>/` and keeps its
metadata cache in `sec/.cache/`.
