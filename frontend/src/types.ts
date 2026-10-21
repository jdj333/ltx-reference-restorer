export type Project = { id: string; name: string; created_at?: string; description?: string };
export type Source = {
  id: string; project_id: string; name: string; path: string; sha256: string; width: number; height: number;
  display_width?: number; duration: number; fps: number; is_vfr: boolean; has_audio: boolean; frame_count?: number;
  metadata?: Record<string, unknown>; media_url: string;
};
export type Placement = { frame: number; x: number; y: number; width: number; height: number };
export type Setup = { actor_id?: string; reference_ids: string[]; keyframes: Placement[]; interpolation: 'linear' | 'hold' };
export type Shot = {
  id: string; name: string; project_id: string; source_id: string; start_time: number; end_time: number;
  frame_start: number; frame_end: number; duration: number; preview_url?: string; setup: Setup;
  frame_map?: { frame: number; source_frame: number; source_timestamp: number; source_pts: number; output_timestamp: number }[];
};
export type Actor = { id: string; project_id: string; name: string };
export type Reference = {
  id: string; project_id: string; actor_id: string; view: 'front' | 'three_quarter' | 'profile'; quality: number;
  approval_status: 'pending' | 'approved' | 'rejected'; provenance: 'original_footage' | 'external_photograph' | 'generated_reconstruction';
  notes?: string; lighting?: string; expression?: string; sha256: string; media_url: string; asset_path?: string;
  crop?: [number, number, number, number]; source_id?: string; timestamp?: number; source_file?: string; original_hash?: string;
};
export type Backend = { id: string; label: string; available: boolean; operations?: string[]; supports_references?: boolean; reason?: string; controls?: string[] };
export type Preset = {
  id: string; label: string;
  settings: { backend: string; scale: number; prompt?: string; seed?: number; use_references?: boolean; steps?: number; cfg?: number };
};
export type Guide = {
  guide_url?: string; artifact_url?: string; transforms?: unknown; kind?: string; description?: string;
  conditioning?: boolean; backend?: string; warnings?: string[]; [key: string]: unknown;
};
export type Job = {
  id: string; shot_id: string; backend: string; state: string; created_at: string; started_at?: string;
  finished_at?: string; error?: string; log?: string | string[]; progress?: number; output_url?: string;
  progress_stage?: string;
  source_preview_url?: string; provenance?: Record<string, unknown>; review_state?: string; version?: number;
  reviews?: { state: string; notes: string; criteria: Record<string, string>; at: string; output_sha256: string }[];
};
export type Note = { id: string; shot_id?: string; actor_id?: string; timestamp?: number; text: string; created_at?: string };
export type ProjectDetail = { project: Project; sources: Source[]; shots: Shot[]; actors: Actor[]; references: Reference[]; jobs: Job[]; notes: Note[] };
