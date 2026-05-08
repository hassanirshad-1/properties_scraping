-- ============================================================================
-- Bawab Database Migration: Add AI-powered smart search columns
-- Run this ONCE against the Bawab Postgres database
-- ============================================================================

-- 1. Add source tracking (for deduplication of scraped listings)
ALTER TABLE properties ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS source_id TEXT UNIQUE;

-- 2. Add AI analysis columns (filled by the scraper's AI image analysis)
ALTER TABLE properties ADD COLUMN IF NOT EXISTS ai_tags TEXT[] DEFAULT '{}';
ALTER TABLE properties ADD COLUMN IF NOT EXISTS ai_vibe TEXT;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS ai_analysis JSONB;

-- 3. Create indexes for fast smart search
CREATE INDEX IF NOT EXISTS idx_properties_ai_tags ON properties USING GIN (ai_tags);
CREATE INDEX IF NOT EXISTS idx_properties_source_url ON properties (source_url);
CREATE INDEX IF NOT EXISTS idx_properties_status ON properties (status);
CREATE INDEX IF NOT EXISTS idx_properties_city ON properties (city);
CREATE INDEX IF NOT EXISTS idx_properties_governorate ON properties (governorate);

-- 4. Full-text search index on titles and descriptions
CREATE INDEX IF NOT EXISTS idx_properties_title_search 
ON properties USING GIN (to_tsvector('simple', COALESCE(title_en, '') || ' ' || COALESCE(title_ar, '')));
