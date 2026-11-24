
export type IngestionStatus =
  | "parsed"
  | "failed"
  | "unavailable"
  | "not_ingested";

export type DirectorySortKey =
  | "market_cap"
  | "change_pct"
  | "week_change_pct"
  | "week_rise_pct"
  | "month_change_pct"
  | "month_rise_pct"
  | "change_52w_pct"
  | "rise_52w_pct"
  | "price_vs_intrinsic_pct";

export type DirectoryOrder = "desc" | "asc";

export interface PriceRange {
  low: number | null;
  high: number | null;
}

export interface WatchItem {
  priority: 1 | 2 | 3;
  text: string;
  /** Free-form classification tag (e.g. FIN / 财报), max 32 chars. */
  code?: string | null;
  /** Server-stamped creation time; absent on legacy items. */
  created_at?: string | null;
  /** Server-stamped last-change time; re-set on every save. */
  updated_at?: string | null;
  /** When this item next deserves attention. */
  next_check_at?: string | null;
}

export interface CompanyDirectoryItem {
  ticker: string;
  name: string;
  sector: string;
  industry: string;
  layer: string;
  layer_name: string;
  segment: string;
  description: string;
  also_in: string[];
  cik: string | null;
  latest_filing_date: string | null;
  latest_filing_status: string | null;
  ingestion_status: IngestionStatus;
  filing_count: number;
  research_available: boolean;
  quality_score?: number | null;
  price?: number | null;
  market_cap?: number | null;
  change_pct?: number | null;
  week_change_pct?: number | null;
  week_rise_pct?: number | null;
  month_change_pct?: number | null;
  month_rise_pct?: number | null;
  change_52w_pct?: number | null;
  rise_52w_pct?: number | null;
  pe?: number | null;
  eps_ttm?: number | null;
  forward_pe?: number | null;
  forward_eps?: number | null;
  /** Mean of each firm's latest sell-side target over the last 12 months. */
  analyst_target?: number | null;
  /** Number of firms with a target in the consensus window. */
  analyst_count?: number | null;
  /** Majority rating: buy, hold, or sell. */
  analyst_rating?: string | null;
  /** Model-derived forward value per share; research cross-check, not a price. */
  intrinsic_value?: number | null;
  /** Current price relative to intrinsic value; negative below, positive above. */
  price_vs_intrinsic_pct?: number | null;
  /** Three-scenario forward prices per share (Bear/Base/Bull, USD). */
  scen_bear?: number | null;
  scen_base?: number | null;
  scen_bull?: number | null;
  quote_as_of?: string | null;
  funnel_tier?: number | null;
  funnel_tier_name?: string | null;
  funnel_tier_source?: string | null;
  funnel_tier_note?: string | null;
  observation_range?: PriceRange;
  entry_range?: PriceRange;
  add_range?: PriceRange;
  reduce_range?: PriceRange;
  watch_items?: WatchItem[];
  annotation_saved?: boolean;
}

export interface CompanyDirectoryView {
  query: string | null;
  layer: string | string[] | null;
  segment: string | string[] | null;
  ingestion_status: IngestionStatus | IngestionStatus[] | null;
  funnel_tier?: number | number[] | null;
  sort_by: DirectorySortKey | null;
  order: DirectoryOrder;
  limit: number;
  offset: number;
  total: number;
  companies: CompanyDirectoryItem[];
}

export interface CatalogSegment {
  name: string;
  count: number;
}

export interface CatalogLayer {
  id: string;
  name: string;
  name_en: string;
  summary: string;
  count: number;
  segments: CatalogSegment[];
}

export interface CatalogLayerListView {
  total_companies: number;
  layers: CatalogLayer[];
}

export interface CompanyView {
  ticker: string;
  name: string;
  cik: string;
  sic: string | null;
  latest_filing_date: string | null;
  latest_filing_status: string;
  filing_count: number;
}

export interface QualityScoreView {
  ticker: string;
  cik: string | null;
  company_name: string;
  sector: string | null;
  rating_cutoff: string;
  calculated_at: string;
  snapshot_id: string;
  rule_version: string;
  semantic_policy: string;
  source_facts_sha256: string | null;
  quality_score: string | null;
  score_available: boolean;
  status: string;
  dimension_count: number | null;
  peer_count: number | null;
  period_ends: string[] | null;
  revenue_growth_dimension: string | null;
  operating_margin_dimension: string | null;
  cash_conversion_dimension: string | null;
  capital_efficiency_dimension: string | null;
  financial_strength_dimension: string | null;
  unknown_reasons: string[];
  v2_hard_status: string | null;
  v2_unknown_reasons: string[];
  v2_hard_gate_count: number | null;
  v2_hard_gate_total: number | null;
  v2_net_debt_ebitda: string | null;
  v2_interest_coverage: string | null;
  v2_cumulative_net_income: string | null;
  v2_cumulative_cfo: string | null;
  v2_positive_operating_income_years: number | null;
  v2_positive_cfo_years: number | null;
}

export interface AnalystFirmView {
  firm: string;
  rating: string | null;
  to_grade: string | null;
  target: number | null;
  prior_target: number | null;
  target_action: string | null;
  action: string | null;
  in_window: boolean;
  action_at: string;
}

export interface AnalystOpinionsView {
  ticker: string;
  as_of: string;
  mean_target: number | null;
  firm_count: number;
  rating_skew: string | null;
  firms: AnalystFirmView[];
}

export interface FilingSummary {
  accession: string;
  form: string;
  filing_date: string | null;
  report_date: string | null;
  status: string;
  parser_version: string | null;
  diagnostics: unknown;
}

export interface FilingListView {
  ticker: string;
  form: string | null;
  limit: number;
  offset: number;
  total: number;
  filings: FilingSummary[];
}

export interface EvidenceView {
  evidence_id: string;
  accession: string;
  relative_path: string | null;
  accession_url: string | null;
  locator_type: string;
  locator_value: string | null;
  content_sha256: string | null;
  excerpt: string | null;
}

export interface FilingView {
  accession: string;
  ticker: string;
  cik: string;
  form: string;
  is_amended: boolean;
  filing_date: string | null;
  report_date: string | null;
  fiscal_year: number | null;
  fiscal_period: string | null;
  primary_document: string | null;
  sec_url: string | null;
  parse: {status: string; parser_version: string | null; diagnostics: unknown};
}

export interface FactItem {
  concept: string;
  label: string | null;
  value_numeric: string | null;
  value_text: string | null;
  unit: string | null;
  end_date: string | null;
  period_type: string | null;
  evidence: EvidenceView;
}

export interface FactView {
  accession: string;
  status: string;
  facts: FactItem[];
}

export interface StatementLine {
  depth: number;
  label: string | null;
  concept: string | null;
  value_numeric: string | null;
  value_text: string | null;
  unit: string | null;
  end_date: string | null;
  period_type: string | null;
  evidence: EvidenceView;
}

export interface StatementView {
  accession: string;
  statement_type: string;
  status: string;
  lines: StatementLine[];
}

export interface SectionView {
  accession: string;
  heading: string | null;
  text: string | null;
  evidence: EvidenceView;
}

export interface TableItem {
  table_id: string;
  table_type: string;
  caption: string | null;
  columns: unknown[] | null;
  rows: unknown[] | null;
  confidence: number | null;
  evidence: EvidenceView;
}

export interface TableView {
  accession: string;
  status: string;
  tables: TableItem[];
}

export interface LayerCompanyNode {
  id: string;
  type: "company";
  ticker: string;
  name: string;
  cik: number | string;
  sector: string;
  industry: string;
  layer: string;
  segment: string;
  description: string;
  also_in: string[];
  cross_in: string[];
  edgar: string;
}

export interface LayerSegmentNode {
  id: string;
  name: string;
  count: number;
  children: LayerCompanyNode[];
}

export interface LayerNode {
  id: string;
  name: string;
  name_en: string;
  count: number;
  summary: string;
  children: LayerSegmentNode[];
}

export interface LayersPayload {
  generated_at?: string;
  stats: {
    companies: number;
    layers: number;
    segments: number;
    cross_layer: number;
  };
  root: {
    id: string;
    name: string;
    count: number;
    children: LayerNode[];
  };
}

/** One company's resolved funnel tier (GET /api/v1/funnel/tiers, keyed by ticker). */
export interface FunnelTierInfo {
  tier: number;
  tier_name: string;
  source: string;
  note: string;
  auto_tier: number;
}

export interface QuotesPayload {
  generated_at: string | null;
  valuation_cache_as_of?: string | null;
  quotes: Record<string, {
    price?: number | null;
    previous_close?: number | null;
    change_pct?: number | null;
    week_change_pct?: number | null;
    week_rise_pct?: number | null;
    month_change_pct?: number | null;
    month_rise_pct?: number | null;
    change_52w_pct?: number | null;
    rise_52w_pct?: number | null;
    pe?: number | null;
    eps_ttm?: number | null;
    forward_pe?: number | null;
    forward_eps?: number | null;
    market_cap?: number | null;
  }>;
}

/** One top mover on the watchlist (GET /api/v1/overview). */
export interface MoverItem {
  ticker: string;
  name: string;
  price: number | null;
  change_pct: number | null;
}

/** Aggregated watchlist + universe indicators (GET /api/v1/overview). */
export interface OverviewView {
  as_of: string | null;
  total_companies: number;
  /** Funnel tier counts, keyed "1" | "2" | "3". */
  tiers: Record<"1" | "2" | "3", number>;
  /** Sum of watchlist market caps in USD; null when no quotes. */
  total_market_cap: number | null;
  /** Mean of available quality scores; null when none computed. */
  avg_quality_score: number | null;
  gainers: MoverItem[];
  losers: MoverItem[];
}

/** One tracked broad-market index (GET /api/v1/market). */
export interface MarketIndexView {
  symbol: string;
  label: string;
  close: number | null;
  change_pct: number | null;
  /** Change over the trailing 5 sessions; null when history is too short. */
  change_1w?: number | null;
  /** Change over the trailing month; null when history is too short. */
  change_1m?: number | null;
  /** Recent closes for the sparkline, oldest first. */
  spark: number[];
}

export interface MarketView {
  as_of: string | null;
  indices: MarketIndexView[];
}

/** One collected news item (GET /api/v1/news). */
export interface NewsItemView {
  id: string;
  title: string;
  url: string;
  source: string;
  published_at: string | null;
}

/** Per-source item counts from the collector (GET /api/v1/news). */
export interface NewsSourceCount {
  source: string;
  count: number;
}

export interface NewsView {
  /** Newest collected_at among returned items; null when empty. */
  as_of: string | null;
  items: NewsItemView[];
  /** Distinct sources present in the store with total counts. */
  sources?: NewsSourceCount[];
}
