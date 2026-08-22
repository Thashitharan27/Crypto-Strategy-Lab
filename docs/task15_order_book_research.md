# Task 15 — order-book research

## Source contracts and limitations

`BOOK_TICKER` is Binance's timestamped best-bid/best-ask event product. The
canonical adapter preserves the update ID, bid/ask prices and quantities,
transaction time, and event time. Availability is the event time. Physical CSV
order is not trusted: rows are ordered by event time and update ID. Identical
update-ID duplicates are deduplicated; conflicting duplicates are errors.

Public USD-M `BOOK_DEPTH` is **not an L5/L10 price-level book**. Its `percentage`
values (normally -5 through -1 and +1 through +5) identify percentage-distance
bands whose supplied `depth` and `notional` values are retained directly. The
code makes no cumulative-versus-incremental assumption and never converts `5%`
to “level 5,” reconstructs prices, calculates walls, or exposes L5/L10 metrics.
Binance `T_DEPTH`, `S_DEPTH`, and `T_DEPTH_BACKFILL` are distinct historical L2
products requiring snapshots, update-ID continuity, and diff reconstruction.
No such source contract is present here, so true L2 reconstruction is not
implemented.

## Compact causal architecture

`OrderBookSnapshotStore` processes one immutable archive partition at a time
and writes Parquet under
`cache/order_book/<book_ticker|book_depth>/<symbol>/1m/<identity>.parquet`, with
an atomic JSON manifest. Schema version 1 identities include the exchange,
market, dataset, symbol, source fingerprint, adapter contract, base interval,
and snapshot/cache versions. Consequently a changed archive invalidates only
its own compact partition; strategy, execution, fee, TP/SL, and reporting
configuration are absent from this identity.

For bucket `[11:59, 12:00)`, only observations strictly before `12:00` belong to
the bucket. The last complete observation is stored with `period_start=11:59`,
`period_end=available_at=12:00`, while `source_event_at` remains the original
event timestamp. Thus 11:59:59.999 is visible at the 12:00 decision and an event
at exactly 12:00 first becomes visible at 12:01. All alignment keys are
explicitly normalized to `datetime64[ns, UTC]`.

The feature layer receives compact resources only. It performs a backward
causal alignment to strategy decision availability and exposes event age as
`available_at - source_event_at`. Raw update IDs, transactions, percentage
rows, and event streams never enter prepared simulator state. The data module
does not import strategy, engine, execution, GUI, or reporting modules.

## Features and staleness

Top-of-book definitions are:

* spread = ask − bid; midpoint = (bid + ask) / 2;
* spread bps = spread / midpoint × 10,000;
* L1 imbalance = (bid quantity − ask quantity) / their sum;
* microprice = (ask price × bid quantity + bid price × ask quantity) / their sum;
* microprice offset bps = (microprice − midpoint) / midpoint × 10,000.

Zero denominators produce `NaN`. For each real percentage band `P`, depth and
notional are exposed separately for bid `-P` and ask `+P`; depth imbalance is
`(bid-depth - ask-depth)/(bid-depth + ask-depth)`, ratio is
`bid-depth/ask-depth`, and notional imbalance uses the analogous notional-only
formula. No opaque pressure signal or trading interpretation is produced.

`book_ticker_max_age_seconds` and `book_depth_max_age_seconds` are research-only
settings and participate in the L2 feature identity. Values older than their
limit become `NaN` and the source-specific stale flag becomes true; there is no
indefinite value forward-fill.

## Coverage and quality

`covered` indicates catalog partition coverage; `observed` indicates a valid
selected source observation. This distinguishes a covered minute with no valid
event from absent archive history. Partial optional source history remains
visible as false coverage and `NaN`. Either ticker or depth may independently
power the provider, but an explicit order-book request with no overlap is an
error. Missing depth bands remain `NaN`, the atomic snapshot is retained,
`book_depth_snapshot_complete` is false, and quality is `WARN`; a prior band's
value is never carried forward.

Quality reuses the Task 12 contracts/cache. Prices must be finite and positive,
quantities/depth/notional finite and non-negative, timestamps valid, and depth
percentage finite and nonzero. Crossed ticker books and conflicting duplicate
keys are errors; locked books and partial depth snapshots are warnings.
Metadata-first quality cache behavior remains unchanged.

These fields are descriptive research context only. They are available through
`research_features`, prepared research context, and the existing causal
trade-row enrichment/reporting path. They do not alter entries, exits, risk,
execution ordering, or simulator semantics.
