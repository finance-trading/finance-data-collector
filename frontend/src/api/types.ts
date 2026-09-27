import type { LinkObject, NodeObject } from "3d-force-graph";

export type IngestionStatus =
  | "parsed"
  | "failed"
  | "unavailable"
  | "not_ingested";

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
}

export interface CompanyDirectoryView {
  query: string | null;
  layer: string | null;
  segment: string | null;
  ingestion_status: IngestionStatus | null;
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

export interface GraphNode extends NodeObject {
  id: number | string;
  ticker: string;
  name: string;
  sector?: string;
  industry?: string;
  layer?: string;
  layer_name?: string;
  segment?: string;
  description?: string;
  edgar?: string;
  color?: string;
}

export type GraphEndpoint = number | string | GraphNode;

export interface GraphLink extends LinkObject<GraphNode> {
  source: GraphEndpoint;
  target: GraphEndpoint;
  type: string;
  weight: number;
  desc?: string;
}

export interface GraphPayload {
  generated_at?: string;
  nodes: GraphNode[];
  links: GraphLink[];
}
