// ============================================================================
// ENHANCED SEARCH ROUTE — Drop-in replacement for Bawab's search.ts
//
// Changes from the original:
// 1. Added ai_tags matching — when user says "balcony", "garden view", etc.
//    it also searches the AI-generated tags from image analysis
// 2. Added view_type and facing filters
// 3. Added floor range filter
// 4. The AI parser now also extracts floor, view, and tag-based criteria
// ============================================================================

import { Router } from "express";
import { getAuth } from "@clerk/express";
import { db, propertiesTable, propertyPhotosTable, aiSearchesTable, usersTable } from "@workspace/db";
import { eq, and, gte, lte, ilike, sql, or, arrayContains } from "drizzle-orm";
import OpenAI from "openai";

const router = Router();

const openai = new OpenAI({
  baseURL: "https://openrouter.ai/api/v1",
  apiKey: process.env.OPENROUTER_API_KEY ?? "placeholder",
});

// Enhanced system prompt — now understands floor, view, sun direction, and AI tags
const SYSTEM_PROMPT = `You are a real estate search assistant for Egypt. The user will describe their ideal property in Arabic or English.
Extract structured search criteria from the user's text.

Return ONLY valid JSON with these optional fields:
{
  "governorate": string,
  "city": string,
  "district": string,
  "type": "APARTMENT"|"VILLA"|"STUDIO"|"DUPLEX"|"PENTHOUSE"|"CHALET"|"COMMERCIAL_OFFICE"|"COMMERCIAL_SHOP"|"LAND",
  "purpose": "RENT"|"SALE",
  "minBedrooms": number,
  "maxBedrooms": number,
  "minPrice": number,
  "maxPrice": number,
  "minArea": number,
  "maxArea": number,
  "furnished": "UNFURNISHED"|"SEMI_FURNISHED"|"FULLY_FURNISHED",
  "hasParking": boolean,
  "hasElevator": boolean,
  "hasPool": boolean,
  "hasGarden": boolean,
  "hasSecurity": boolean,
  "minFloor": number,
  "maxFloor": number,
  "viewType": string,
  "facing": string,
  "searchTags": [string],
  "summary": "brief Arabic summary of what was searched"
}

IMPORTANT:
- "searchTags" should contain keywords describing what the user wants that aren't covered by other fields
  Examples: ["garden view", "natural light", "modern", "quiet area", "north facing", "high floor", "compound"]
- For Egyptian floor naming: Ground = 0, L1 = 1, L2 = 2, etc.
- "viewType" can be: "garden", "street", "pool", "city", "compound", "nile", "desert", "sea"
- "facing" can be: "north", "south", "east", "west"
- Only include fields that are clearly mentioned. All prices are in EGP.`;

async function parseQuery(query: string): Promise<Record<string, unknown>> {
  if (!process.env.OPENROUTER_API_KEY) {
    return {};
  }
  try {
    const completion = await openai.chat.completions.create({
      model: "anthropic/claude-3-haiku",
      messages: [
        { role: "system", content: SYSTEM_PROMPT },
        { role: "user", content: query },
      ],
      response_format: { type: "json_object" },
      max_tokens: 512,
    });
    const content = completion.choices[0]?.message?.content ?? "{}";
    return JSON.parse(content);
  } catch {
    return {};
  }
}

// POST /api/v1/search/smart
router.post("/smart", async (req, res) => {
  const { userId } = getAuth(req);
  const { query } = req.body;

  if (!query) {
    res.status(400).json({ error: "query is required" });
    return;
  }

  const criteria = await parseQuery(query);
  const conditions = [eq(propertiesTable.status, "ACTIVE")];

  // Standard filters
  if (criteria.governorate) conditions.push(ilike(propertiesTable.governorate, `%${criteria.governorate}%`));
  if (criteria.city) conditions.push(ilike(propertiesTable.city, `%${criteria.city}%`));
  if (criteria.district) conditions.push(ilike(propertiesTable.district, `%${criteria.district}%`));
  if (criteria.type) conditions.push(eq(propertiesTable.type, criteria.type as any));
  if (criteria.purpose) conditions.push(eq(propertiesTable.purpose, criteria.purpose as any));
  if (criteria.minBedrooms) conditions.push(gte(propertiesTable.bedrooms, criteria.minBedrooms as number));
  if (criteria.maxBedrooms) conditions.push(lte(propertiesTable.bedrooms, criteria.maxBedrooms as number));
  if (criteria.minPrice) conditions.push(gte(propertiesTable.price, criteria.minPrice as number));
  if (criteria.maxPrice) conditions.push(lte(propertiesTable.price, criteria.maxPrice as number));
  if (criteria.minArea) conditions.push(gte(propertiesTable.area, criteria.minArea as number));
  if (criteria.maxArea) conditions.push(lte(propertiesTable.area, criteria.maxArea as number));
  if (criteria.furnished) conditions.push(eq(propertiesTable.furnished, criteria.furnished as any));
  if (criteria.hasParking === true) conditions.push(eq(propertiesTable.hasParking, true));
  if (criteria.hasElevator === true) conditions.push(eq(propertiesTable.hasElevator, true));
  if (criteria.hasPool === true) conditions.push(eq(propertiesTable.hasPool, true));
  if (criteria.hasGarden === true) conditions.push(eq(propertiesTable.hasGarden, true));
  if (criteria.hasSecurity === true) conditions.push(eq(propertiesTable.hasSecurity, true));

  // NEW: Floor filter
  if (criteria.minFloor) conditions.push(gte(propertiesTable.floor, criteria.minFloor as number));
  if (criteria.maxFloor) conditions.push(lte(propertiesTable.floor, criteria.maxFloor as number));

  // NEW: View type filter (searches the view_type array column)
  if (criteria.viewType) {
    conditions.push(sql`${criteria.viewType} = ANY(${propertiesTable.viewType})`);
  }

  // NEW: Facing/sun direction filter
  if (criteria.facing) {
    conditions.push(ilike(propertiesTable.facing, `%${criteria.facing}%`));
  }

  // NEW: AI tags search — match against the ai_tags array column
  const searchTags = (criteria.searchTags as string[]) ?? [];
  if (searchTags.length > 0) {
    // Match properties that have ANY of the requested tags
    const tagConditions = searchTags.map(tag =>
      sql`EXISTS (SELECT 1 FROM unnest(${propertiesTable}.ai_tags) AS t WHERE t ILIKE ${'%' + tag + '%'})`
    );
    conditions.push(or(...tagConditions)!);
  }

  const properties = await db
    .select()
    .from(propertiesTable)
    .where(and(...conditions))
    .limit(20);

  const withPhotos = await Promise.all(
    properties.map(async (p) => {
      const [photo] = await db
        .select()
        .from(propertyPhotosTable)
        .where(eq(propertyPhotosTable.propertyId, p.id))
        .orderBy(propertyPhotosTable.order)
        .limit(1);
      return { ...p, coverPhoto: photo?.url ?? null };
    })
  );

  if (userId) {
    const [user] = await db.select().from(usersTable).where(eq(usersTable.clerkId, userId)).limit(1);
    if (user) {
      await db.insert(aiSearchesTable).values({
        userId: user.id,
        query,
        parsedCriteria: JSON.stringify(criteria),
        resultPropertyIds: withPhotos.map((p) => p.id),
        resultCount: String(withPhotos.length),
      });
    }
  }

  res.json({
    properties: withPhotos,
    parsedCriteria: criteria,
    total: withPhotos.length,
  });
});

// GET /api/v1/search/history
router.get("/history", async (req, res) => {
  const { userId } = getAuth(req);
  if (!userId) {
    res.json([]);
    return;
  }

  const [user] = await db.select().from(usersTable).where(eq(usersTable.clerkId, userId)).limit(1);
  if (!user) {
    res.json([]);
    return;
  }

  const history = await db
    .select()
    .from(aiSearchesTable)
    .where(eq(aiSearchesTable.userId, user.id))
    .orderBy(aiSearchesTable.createdAt)
    .limit(20);

  res.json(history.map((h) => ({ id: h.id, query: h.query, resultCount: h.resultCount, createdAt: h.createdAt })));
});

export default router;
