/** Shared browser-facing video-filter and facet contracts. */
export interface VideoFilters {
  language: string | null;
  category: string | null;
  tag: string | null;
  instance: string | null;
}

export interface FacetValue {
  value: string;
  count: number;
}

export interface LanguageFacet extends FacetValue {
  label?: string | null;
}

export interface CategoryFacet extends FacetValue {
  category_id: string | null;
}

export interface VideoFacetsPayload {
  languages: LanguageFacet[];
  categories: CategoryFacet[];
  tags: FacetValue[];
  instances: FacetValue[];
  coverage: {
    language: {
      known: number;
      unknown: number;
      total: number;
      ratio: number;
    };
  };
  meta?: {
    dynamic?: boolean;
    tag_limit?: number;
    instance_limit?: number;
  };
}
