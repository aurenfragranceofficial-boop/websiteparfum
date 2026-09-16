# AUREN — Perfume Marketplace (PRD)

## Original Problem Statement
Membangun marketplace parfum modern "AUREN" (Bahasa Indonesia) untuk jual beli parfum baru/original & preloved, plus titip jual (community seller) yang direview admin. Terasa seperti marketplace nyata, bukan landing page. Tagline: "Find Your Signature Scent."

## Architecture
- **Backend**: FastAPI (`/app/backend/server.py`), MongoDB (motor). All routes under `/api`.
- **Auth**: Custom JWT (email+password, bcrypt). Bearer token in `localStorage` (`auren_token`). Admin-only.
- **Frontend**: React 19 + React Router 7, Tailwind, shadcn/ui, lucide-react, sonner toasts.
- **Storage**: Product/submission photos = client-compressed base64 stored in Mongo.
- **Design**: Ivory/cream (#FAFAF7), obsidian (#121212), champagne gold (#C5A059). Playfair Display + Outfit fonts. Mobile-first with bottom nav.

## User Personas
1. **Buyer** — browses, wishlists, expresses interest (no login); AUREN contacts them.
2. **Seller (Community)** — submits perfume via form, tracks status by Listing ID + phone.
3. **Admin/Owner** — manages products, submissions, interests, contacts via `/admin`.

## Core Requirements (static)
- Browse → Product Detail → I'm Interested → Contact (via AUREN, no online payment).
- Sell → Submit → Admin Review → Accept → Create Product → Listed → Sold.
- All form data persists to DB; admin fully manages products & submissions.

## Implemented (2026-06)
- Home (hero, featured, categories, how it works, recently viewed, CTA).
- Shop: search (name/brand/notes/category), filters (category/brand/gender/size/price), sort, pagination.
- Product Detail: gallery, notes pyramid, seller/status, badges, Interested dialog, Contact Seller (WhatsApp), share/copy link, wishlist.
- Sell form (seller+perfume info, 5 photo slots w/ preview, agreement) → Submission Received + ref ID.
- Track submission (ref + phone) with status stepper.
- Trust & Safety, About, Contact (+FAQ accordion), Favorites, Profile.
- Admin: login, overview KPIs, product CRUD + status, submission management + Create-Product-From-Submission, interests, contacts, notification badges.
- Wishlist & recently-viewed in localStorage. Mobile bottom nav.
- Sample data: 13 products + 2 submissions + admin seeded on startup.
- Verified end-to-end by testing agent (100% of tested flows).

## Backlog / Remaining
- **P1**: Dark/light mode toggle; editable announcement banner (admin-managed settings).
- **P2**: Object storage/GridFS for photos (currently base64); pagination for submissions/interests/contacts; split server.py into route modules; simple analytics charts.

## Test Credentials
Admin: ethanphillipk@gmail.com / AurenAdmin2026 (see /app/memory/test_credentials.md)
