# My agent: Sharent Marketplace Concierge
One-liner: A conversational agent that helps owners and renters discover, list, book, and safely transact household goods with a catalog of rentable items and transparent fee/deposit calculations.

Tool coverage:
- Memory: Remembers user profile (Owner vs Renter), location, verified status, previous rental history, ratings, and preferences (favorite categories, budget).
- Tools:
  - Search & filter catalog (`search_items`, `get_item_details`)
  - Create listing for owners (`create_listing`)
  - Calculate rental costs, insurance, service fees, and owner net payout (`calculate_rental_quote`)
  - Submit rental inquiries and accept agreements (`create_rental_booking`)
  - Submit ratings & reviews for items, owners, and renters (`submit_review`)
- Catalog/UI: Catalog of household items (power tools, party equipment, appliances, lawncare, apparel) rendered as rich A2UI cards and transaction breakdown tables.
- Image gen: Generates listing preview images or product condition inspection visuals for listed items.
- Sandbox: Accurate computation of tiered service fees ($1 + 5% of rent), insurance rates, duration checks against min/max limits, and deposit deductions for damages.

Recommended for every project: memory, storage, tools, image generation, A2UI
Agent-specific / stretch (pick what fits): Code sandbox for fee and escrow arithmetic, Firestore for persistent listings/bookings, Google Maps API for pickup/return meeting points.
