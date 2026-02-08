export interface ChannelRow {
  channel_id: string;
  channel_name: string | null;
  channel_url: string | null;
  display_name: string | null;
  instance_domain: string;
  videos_count: number | null;
  followers_count: number | null;
  avatar_url: string | null;
  health_status: string | null;
  health_checked_at: number | null;
  health_error: string | null;
  last_error: string | null;
  last_error_at: number | null;
  last_error_source: string | null;
}

export interface ChannelsPayload {
  generatedAt?: number;
  total?: number;
  rows?: ChannelRow[];
}
