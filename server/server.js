/* Itanva sync service — name + 4-digit PIN accounts (optional) that carry reading state across devices.
   Stores one JSON blob per reader (progress, shelf, notes, stats, profile, prefs). No email, no tracking.
   Env: DATABASE_URL (Postgres; tables live in schema "itanva"), ALLOWED_ORIGINS (comma list), PORT. */
"use strict";
const express = require("express");
const { Pool } = require("pg");
const crypto = require("crypto");

const PORT = process.env.PORT || 10000;
const ORIGINS = (process.env.ALLOWED_ORIGINS || "https://itanva.com,https://www.itanva.com,https://itanva.onrender.com,https://bibli-preview.onrender.com,http://localhost:8799,http://127.0.0.1:8799,http://127.0.0.1:8798").split(",").map(s => s.trim());
const MAX_STATE = 300 * 1024;
const pool = new Pool({ connectionString: process.env.DATABASE_URL, ssl: process.env.DATABASE_URL && !/localhost|127\.0\.0\.1|render\.com:5432\/.*internal|\.internal/.test(process.env.DATABASE_URL) ? { rejectUnauthorized: false } : false, max: 5 });

async function migrate() {
  await pool.query(`
    CREATE SCHEMA IF NOT EXISTS itanva;
    CREATE TABLE IF NOT EXISTS itanva.readers (
      id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,
      pin_hash TEXT NOT NULL, created TIMESTAMPTZ NOT NULL DEFAULT now(), last_seen TIMESTAMPTZ NOT NULL DEFAULT now());
    CREATE TABLE IF NOT EXISTS itanva.sessions (
      token_hash TEXT PRIMARY KEY, reader_id BIGINT NOT NULL REFERENCES itanva.readers(id) ON DELETE CASCADE,
      created TIMESTAMPTZ NOT NULL DEFAULT now(), last_used TIMESTAMPTZ NOT NULL DEFAULT now());
    CREATE TABLE IF NOT EXISTS itanva.states (
      reader_id BIGINT PRIMARY KEY REFERENCES itanva.readers(id) ON DELETE CASCADE,
      data JSONB NOT NULL, updated TIMESTAMPTZ NOT NULL DEFAULT now());`);
}

// ---- helpers
const nameKey = n => n.normalize("NFKC").toLowerCase().replace(/\s+/g, " ").trim();
const validName = n => typeof n === "string" && /^[\p{L}\p{N} .'’-]{2,24}$/u.test(n.trim());
const validPin = p => typeof p === "string" && /^\d{4}$/.test(p);
const hashPin = (pin, salt) => new Promise((res, rej) => crypto.scrypt(pin, salt, 32, { N: 16384 }, (e, k) => e ? rej(e) : res(k.toString("hex"))));
const makeHash = async pin => { const salt = crypto.randomBytes(16).toString("hex"); return salt + ":" + await hashPin(pin, salt); };
const checkHash = async (pin, stored) => { const [salt, h] = stored.split(":"); const k = await hashPin(pin, salt); return crypto.timingSafeEqual(Buffer.from(k, "hex"), Buffer.from(h, "hex")); };
const sha = s => crypto.createHash("sha256").update(s).digest("hex");

// in-memory rate limiting: 6 failed attempts per name or IP per 15 min
const attempts = new Map();
function limited(key) { const now = Date.now(); const a = (attempts.get(key) || []).filter(t => now - t < 15 * 60e3); attempts.set(key, a); return a.length >= 6; }
function failed(key) { (attempts.get(key) || attempts.set(key, []).get(key)).push(Date.now()); }
setInterval(() => { const now = Date.now(); for (const [k, a] of attempts) if (!a.some(t => now - t < 15 * 60e3)) attempts.delete(k); }, 60e3).unref();

async function auth(req, res, next) {
  const m = /^Bearer ([a-f0-9]{64})$/.exec(req.get("authorization") || "");
  if (!m) return res.status(401).json({ error: "no_session" });
  const r = await pool.query("UPDATE itanva.sessions SET last_used=now() WHERE token_hash=$1 RETURNING reader_id", [sha(m[1])]);
  if (!r.rowCount) return res.status(401).json({ error: "no_session" });
  req.readerId = r.rows[0].reader_id; next();
}

// ---- app
const app = express();
app.set("trust proxy", 1);
app.use((req, res, next) => {
  const o = req.get("origin");
  if (o && ORIGINS.includes(o)) { res.set("Access-Control-Allow-Origin", o); res.set("Vary", "Origin"); res.set("Access-Control-Allow-Headers", "Content-Type, Authorization"); res.set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS"); }
  if (req.method === "OPTIONS") return res.sendStatus(204);
  next();
});
app.use(express.json({ limit: MAX_STATE + 4096 }));

app.get("/", (req, res) => res.json({ service: "itanva-sync", ok: true }));
app.get("/health", async (req, res) => { try { await pool.query("SELECT 1"); res.json({ ok: true }); } catch (e) { res.status(500).json({ ok: false }); } });

app.post("/api/signup", async (req, res) => {
  const { name, pin, state } = req.body || {};
  if (!validName(name)) return res.status(400).json({ error: "bad_name" });
  if (!validPin(pin)) return res.status(400).json({ error: "bad_pin" });
  const key = nameKey(name);
  if (limited("ip:" + req.ip)) return res.status(429).json({ error: "too_many" });
  const exists = await pool.query("SELECT 1 FROM itanva.readers WHERE name_key=$1", [key]);
  if (exists.rowCount) return res.status(409).json({ error: "name_taken" });
  const r = await pool.query("INSERT INTO itanva.readers(name,name_key,pin_hash) VALUES($1,$2,$3) RETURNING id", [name.trim(), key, await makeHash(pin)]);
  const token = crypto.randomBytes(32).toString("hex");
  await pool.query("INSERT INTO itanva.sessions(token_hash,reader_id) VALUES($1,$2)", [sha(token), r.rows[0].id]);
  if (state && JSON.stringify(state).length <= MAX_STATE) await pool.query("INSERT INTO itanva.states(reader_id,data) VALUES($1,$2)", [r.rows[0].id, state]);
  res.json({ token, name: name.trim() });
});

app.post("/api/login", async (req, res) => {
  const { name, pin } = req.body || {};
  if (!validName(name) || !validPin(pin)) return res.status(400).json({ error: "bad_credentials" });
  const key = nameKey(name);
  if (limited("ip:" + req.ip) || limited("name:" + key)) return res.status(429).json({ error: "too_many" });
  const r = await pool.query("SELECT id,name,pin_hash FROM itanva.readers WHERE name_key=$1", [key]);
  if (!r.rowCount || !(await checkHash(pin, r.rows[0].pin_hash))) { failed("ip:" + req.ip); failed("name:" + key); return res.status(401).json({ error: "bad_credentials" }); }
  const token = crypto.randomBytes(32).toString("hex");
  await pool.query("INSERT INTO itanva.sessions(token_hash,reader_id) VALUES($1,$2)", [sha(token), r.rows[0].id]);
  await pool.query("UPDATE itanva.readers SET last_seen=now() WHERE id=$1", [r.rows[0].id]);
  const s = await pool.query("SELECT data, updated FROM itanva.states WHERE reader_id=$1", [r.rows[0].id]);
  res.json({ token, name: r.rows[0].name, state: s.rowCount ? s.rows[0].data : null, updated: s.rowCount ? s.rows[0].updated : null });
});

app.get("/api/state", auth, async (req, res) => {
  const s = await pool.query("SELECT data, updated FROM itanva.states WHERE reader_id=$1", [req.readerId]);
  res.json({ state: s.rowCount ? s.rows[0].data : null, updated: s.rowCount ? s.rows[0].updated : null });
});
app.put("/api/state", auth, async (req, res) => {
  const { state } = req.body || {};
  if (!state || typeof state !== "object" || JSON.stringify(state).length > MAX_STATE) return res.status(400).json({ error: "bad_state" });
  await pool.query("INSERT INTO itanva.states(reader_id,data,updated) VALUES($1,$2,now()) ON CONFLICT (reader_id) DO UPDATE SET data=EXCLUDED.data, updated=now()", [req.readerId, state]);
  res.json({ ok: true });
});
app.post("/api/logout", auth, async (req, res) => { await pool.query("DELETE FROM itanva.sessions WHERE token_hash=$1", [sha(req.get("authorization").slice(7))]); res.json({ ok: true }); });
app.post("/api/pin", auth, async (req, res) => {
  const { pin, newPin } = req.body || {};
  if (!validPin(pin) || !validPin(newPin)) return res.status(400).json({ error: "bad_pin" });
  const r = await pool.query("SELECT pin_hash FROM itanva.readers WHERE id=$1", [req.readerId]);
  if (!(await checkHash(pin, r.rows[0].pin_hash))) return res.status(401).json({ error: "bad_credentials" });
  await pool.query("UPDATE itanva.readers SET pin_hash=$1 WHERE id=$2", [await makeHash(newPin), req.readerId]); res.json({ ok: true });
});
app.delete("/api/account", auth, async (req, res) => { await pool.query("DELETE FROM itanva.readers WHERE id=$1", [req.readerId]); res.json({ ok: true }); });
app.use((err, req, res, next) => { console.error(err); res.status(500).json({ error: "server" }); });

migrate().then(() => app.listen(PORT, () => console.log("itanva-sync on", PORT))).catch(e => { console.error("migration failed", e); process.exit(1); });
