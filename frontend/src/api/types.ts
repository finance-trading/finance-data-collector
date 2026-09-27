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
