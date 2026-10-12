/** Staging-only operational evidence store; never bootstraps canonical schema. */
import Database from "better-sqlite3";
import type { VideoDetailResult } from "../video-detail.js";

/** Original production PK and exact remote UUID snapshot. */
export interface AvailabilityWorkRow {
  video_id: string;
  instance_domain: string;
  video_uuid: string;
}
const TABLE_SQL = `CREATE TABLE video_availability_work (
  video_id TEXT NOT NULL, instance_domain TEXT NOT NULL, video_uuid TEXT NOT NULL,
  outcome TEXT CHECK (outcome IS NULL OR outcome IN ('available','not_found','gone','unknown')),
  checked_at INTEGER, error TEXT, PRIMARY KEY(video_id,instance_domain))`;
const INDEX_SQL = `CREATE INDEX idx_availability_work_host_identity ON video_availability_work
 (lower(trim(instance_domain)),video_id,instance_domain)`;
/** DDL includes CHECK, original PK, and exact index expression/order. */
function fingerprint(sql: string): string {
  // Preserve literal outcome labels while ignoring formatting of SQL syntax.
  return sql
    .split(/('(?:''|[^'])*')/)
    .map((part, i) =>
      i % 2
        ? part
        : part
            .toLowerCase()
            .replace(/\s/g, "")
            .replace(/ifnotexists/g, ""),
    )
    .join("")
    .replace(/;$/, "");
}

/** Persist only bounded classifier facts, never remote error text or URL secrets. */
function diagnosticKind(kind: string): string {
  if (
    !/^(unsafe_host|unknown|network|tls|timeout|invalid_json|http_[1-5][0-9]{2})$/.test(
      kind,
    )
  ) {
    throw new Error("Invalid availability diagnostic classification");
  }
  return kind;
}

/** Own only pending result updates in an already initialized updater corpus. */
export class VideoAvailabilityWorkStore {
  private readonly db: Database.Database;
  /** Open existing staging only; validate provenance and schema before writes. */
  constructor(dbPath: string) {
    this.db = new Database(dbPath, { fileMustExist: true });
    try {
      for (const [key, value] of [
        ["video_corpus_role", "updater_staging_delta"],
        ["video_availability_semantics", "canonical_absence_atomic_ingest_v2"],
      ]) {
        const row = this.db
          .prepare("SELECT value FROM crawl_state WHERE key=?")
          .get(key) as { value: string } | undefined;
        if (row?.value !== value)
          throw new Error(
            "Availability worker requires current updater staging corpus",
          );
      }
      for (const [name, sql] of [
        ["video_availability_work", TABLE_SQL],
        ["idx_availability_work_host_identity", INDEX_SQL],
      ]) {
        const row = this.db
          .prepare("SELECT sql FROM sqlite_master WHERE name=?")
          .get(name) as { sql: string } | undefined;
        if (!row?.sql || fingerprint(row.sql) !== fingerprint(sql))
          throw new Error(
            "Incompatible availability work schema; recreate staging",
          );
      }
      const invalid = this.db
        .prepare(
          `SELECT COUNT(*) AS n FROM video_availability_work
        WHERE outcome IS NOT NULL OR checked_at IS NOT NULL OR error IS NOT NULL
        OR typeof(video_id)!='text' OR typeof(instance_domain)!='text'
        OR typeof(video_uuid)!='text' OR length(trim(video_uuid))=0`,
        )
        .get() as { n: number };
      if (invalid.n)
        throw new Error("Availability work must be fresh pending identities");
      this.db.pragma("journal_mode = WAL");
    } catch (error) {
      this.db.close();
      throw error;
    }
  }
  /** Retain host keys, never an unbounded video result set. */
  hosts(): string[] {
    return (
      this.db
        .prepare(
          `SELECT lower(trim(instance_domain)) AS host_key FROM video_availability_work
      GROUP BY lower(trim(instance_domain)) ORDER BY host_key`,
        )
        .all() as { host_key: string }[]
    ).map((r) => r.host_key);
  }
  /** Fully consume at most 250 rows before any network await. */
  pendingBatch(
    host: string,
    cursor?: Pick<AvailabilityWorkRow, "video_id" | "instance_domain">,
  ): AvailabilityWorkRow[] {
    const range = cursor ? "AND (video_id,instance_domain) > (?,?)" : "";
    return this.db
      .prepare(
        `SELECT video_id,instance_domain,video_uuid FROM video_availability_work
      WHERE lower(trim(instance_domain))=? AND outcome IS NULL ${range}
      ORDER BY video_id,instance_domain LIMIT 250`,
      )
      .all(
        ...(cursor ? [host, cursor.video_id, cursor.instance_domain] : [host]),
      ) as AvailabilityWorkRow[];
  }
  /** Guard exact immutable PK/UUID and pending state; a duplicate is fatal. */
  recordResult(
    row: AvailabilityWorkRow,
    result: VideoDetailResult<Record<string, unknown>>,
  ): void {
    if (
      !["available", "not_found", "gone", "unknown"].includes(result.kind) ||
      !Number.isSafeInteger(result.checkedAt) ||
      result.checkedAt < 0
    )
      throw new Error("Invalid detail result");
    // Classification carries no remote payload or secret URL. Persist bounded facts.
    const error =
      result.kind === "unknown"
        ? `detail: ${diagnosticKind(result.error.classification.kind)}`
        : null;
    const write = this.db
      .prepare(
        `UPDATE video_availability_work SET outcome=?,checked_at=?,error=?
      WHERE video_id=? AND instance_domain=? AND video_uuid=? AND outcome IS NULL`,
      )
      .run(
        result.kind,
        result.checkedAt,
        error,
        row.video_id,
        row.instance_domain,
        row.video_uuid,
      );
    if (write.changes !== 1)
      throw new Error(
        "Availability work identity/pending write invariant violated",
      );
  }
  /** Indexed normalized-host bulk skip; no per-video absence or timestamp. */
  markHostPreflightUnknown(host: string, diagnostic: string): void {
    this.db
      .prepare(
        `UPDATE video_availability_work SET outcome='unknown',checked_at=NULL,error=?
      WHERE lower(trim(instance_domain))=? AND outcome IS NULL`,
      )
      .run(`host_preflight: ${diagnosticKind(diagnostic)}`, host);
  }
  /** Refuse process success while any selected identity lacks terminal evidence. */
  assertComplete(): void {
    const row = this.db
      .prepare(
        `SELECT COUNT(*) FILTER (WHERE outcome IS NULL) AS unfinished,
      COUNT(*) FILTER (WHERE checked_at IS NULL AND
        (outcome IS NOT 'unknown' OR error IS NULL OR error NOT LIKE 'host_preflight: %')) AS invalid
      FROM video_availability_work`,
      )
      .get() as { unfinished: number; invalid: number };
    if (row.unfinished || row.invalid)
      throw new Error("Availability work incomplete or inconsistent");
  }
  /** Close on success and fatal failures after all outstanding operations drain. */
  close(): void {
    this.db.close();
  }
}
