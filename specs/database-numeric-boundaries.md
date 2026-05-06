# database-numeric-boundaries.md

> **Status**: v1.0.0 (new in v0.11.0). Defines the canonical rule for **money / quantity / decimal column boundaries** between the database and the application: explicit coercion at the ORM boundary, never per-call. Surfaced by openTrattOS m2-cost-rollup-and-audit (`numeric` columns serialised as strings; multiplication produced `"1000NaN"`; required scattered `Number(...)` calls). Reinforces and generalises AGENTS.md universal rule "**no float for money**".

## 1. Why this spec

A recurring data-integrity hazard surfaced in openTrattOS m2-cost-rollup-and-audit:

> Postgres `numeric` columns deserialise to **strings** through TypeORM (default behaviour); JavaScript multiplication of strings produces NaN if non-numeric chars are present, or string concatenation if both are strings. `'10' * '5' === 50` (coerced) but `'10.50' * '5' === 52.5` and `'10' + '5' === '105'` and `'10.5' + 0.1 === '10.50.1'`. Subtle, deterministic, silent.

A bug from the retro: cost rollup multiplied `recipe_cost: "10.50"` by `unit_quantity: 5` (number) producing `"52.5"`, then concatenated with logging prefix → `"Total: 1052.5"` (string concat), shipped to the audit log as a string, and downstream BI ingest crashed on `"1000NaN"` for a different recipe where `recipe_cost = NULL` got serialised as `"null"` → `null * 5 === NaN`.

The same hazard exists in:

- **TypeORM** (`numeric`, `decimal` → string by default; `bigint` → string).
- **Prisma** (`Decimal` → `Decimal.js` instance, but JSON serialisation falls back to string).
- **Sequelize** (similar to TypeORM).
- **Sqlx (Rust)** ergonomic mapping but `BigDecimal` requires explicit feature flag.
- **SQLAlchemy** (Python) — `Numeric` returns `decimal.Decimal` only if you specified `Numeric` in the column type; if you used `Float`, you get IEEE-754 `float` (silent precision loss for money).

The fix is **the same in every stack**: declare the coercion at the ORM boundary, not at each call site.

---

## 2. The rule

> **Every monetary, quantity, or precision-sensitive column MUST declare its application-side type at the ORM column definition. The application code MUST NEVER call `Number(...)`, `parseFloat(...)`, `float(...)`, etc. on a value coming from this column.**

If the conversion is needed, it lives in **one place** — a column transformer (TypeORM), a custom type (Prisma / SQLAlchemy), or a mapping layer (SQL).

---

## 3. Per-stack recipes

### 3.1 TypeORM (the openTrattOS hazard)

```ts
// ❌ Forbidden: column declared without transformer; consumer code calls Number()
@Entity()
export class Recipe {
  @Column('numeric', { precision: 10, scale: 2 })
  cost: string;  // arrives as string; consumers must Number(cost)
}

// ✅ Required: transformer at the boundary; consumer code receives Decimal
import { Decimal } from 'decimal.js';

const decimalTransformer = {
  to: (value: Decimal | null) => value?.toString() ?? null,
  from: (value: string | null) => value ? new Decimal(value) : null,
};

@Entity()
export class Recipe {
  @Column('numeric', { precision: 10, scale: 2, transformer: decimalTransformer })
  cost: Decimal;  // arrives as Decimal; arithmetic uses Decimal API
}
```

Discipline:
- One transformer per column type (decimal, decimal-nullable, bigint, etc.) — declared in `apps/api/src/db/transformers.ts`.
- Decimal arithmetic uses `decimal.js` (or `big.js`) — never JS native `*`/`+`/`-` on the value.
- Logging serialisation: `cost.toString()` explicitly; no `${cost}` string interpolation (which calls `.toString()` but inconsistently for Decimal subclasses).

### 3.2 Python / SQLAlchemy

```python
# ❌ Forbidden: float column for money
class Recipe(Base):
    cost: Mapped[float] = mapped_column(Float)  # IEEE-754; precision loss

# ✅ Required: Numeric → Decimal end-to-end
from decimal import Decimal
from sqlalchemy import Numeric

class Recipe(Base):
    cost: Mapped[Decimal] = mapped_column(Numeric(10, 2))
```

Discipline:
- Migrations declare `Numeric` (or `DECIMAL`); never `Float` for money.
- DTOs use `Decimal` (or `pydantic.condecimal`); never `float`.
- JSON serialisation: `pydantic.BaseModel.model_dump(mode='json')` produces a string; consumers parse back to Decimal. NEVER `float(value)` at the boundary.

### 3.3 Prisma

```prisma
model Recipe {
  cost Decimal @db.Decimal(10, 2)
}
```

Prisma returns `Prisma.Decimal` (decimal.js wrapper) for `Decimal` fields. Discipline:
- Never call `.toNumber()` on a `Decimal` from a money column — precision loss.
- JSON serialisation in API responses: explicit `cost.toFixed(2)` (the API layer's contract is the precision spec).

### 3.4 Plain SQL + bare driver

If using a bare driver (`pg`, `psycopg`, `sqlite3`, `mysql2`):

- Most drivers return `numeric` as string in their default modes. Don't fight the driver — accept the string at the row-fetch boundary, parse to Decimal once.
- Encapsulate the parse in a row-mapper: `function mapRecipeRow(row: RawRow): Recipe { return { ..., cost: new Decimal(row.cost) }; }`. Every call to the row-fetch path goes through the mapper.

### 3.5 Elixir / Ecto

```elixir
field :cost, :decimal  # Ecto returns Decimal struct
```

Decimal arithmetic via `Decimal` module. Same rule: never `Decimal.to_float/1` for money.

---

## 4. Edge cases

### 4.1 Aggregations and `SUM(numeric)`

Postgres `SUM(numeric)` returns `numeric`. Same boundary rule applies: the result hits the application as a string (TypeORM) or Decimal (SQLAlchemy with Numeric). No special-casing.

If you need raw SQL aggregations with mixed-type math, cast inside SQL: `SUM(numeric_col)::numeric(10,2)` — keep the result in numeric domain until it reaches the boundary.

### 4.2 Nullable columns

A `numeric NULL` column returns `null` in TypeORM (not `"null"` — that's a separate JSON-bug). Transformer's `from(null) === null`; downstream code uses `if (cost === null)` (or `if (cost == null)` to also catch undefined).

### 4.3 Money + currency

A "money" column is **numeric + a currency code**. Don't store the currency in the same column (encoding "EUR 10.50" as a string is the worst of all worlds). Two columns: `cost: Decimal` + `currency: text` (with a CHECK constraint on ISO 4217 codes). Consumer code carries both.

### 4.4 Performance

`Decimal` arithmetic is ~10x slower than IEEE-754 `float`. Acceptable for transactional code; not for hot inner loops over millions of rows. For analytics:
- Aggregate inside SQL (Postgres `numeric` arithmetic is fast at scale).
- For ML / statistical work, accept the precision loss explicitly: `parseFloat(cost.toString())` at the model-feature boundary, with a logged note that the conversion is intentional.

---

## 5. Anti-patterns

- **`Float`, `float`, `double`, or any IEEE-754 column type for money / quantity**: forbidden per AGENTS.md universal rule.
- **`Number(value)` / `parseFloat(value)` on values from numeric columns**: forbidden per §2 (centralise via transformer).
- **`SUM(numeric)::float8` in SQL**: forbidden — the cast loses precision before the boundary.
- **String interpolation `${cost}` for money in user-facing output**: forbidden — explicit `.toFixed(N)` or locale-aware `Intl.NumberFormat`.
- **Comparing money via `===` / `==` on string values**: forbidden — `'10.50' !== '10.5'` but they're the same money. Compare via Decimal API: `a.equals(b)`.
- **JSON serialising a `Decimal` via `JSON.stringify(value)` directly**: forbidden — the result depends on the Decimal lib's `toJSON()` definition (some emit string, some emit number, some throw). Always use the API layer's explicit serialiser.

---

## 6. Cross-references

- AGENTS.md universal rule: "no float for money" — generalised here.
- [event-and-data-patterns.md](event-and-data-patterns.md) §6 (open-enum text columns + CHECK) — sister pattern for non-numeric column conventions.
- [release-management.md](release-management.md) §6.4 — anti-collision contract; numeric column ADD-COLUMNS use Shape A or B per [cross-slice-additive-extension.md](cross-slice-additive-extension.md).

---

## 7. Reference implementations

| Project | Surface | Recipe |
|---|---|---|
| openTrattOS | `recipes.cost`, `ingredients.unit_cost` | TypeORM `@Column('numeric', { transformer })` with decimal.js |
| openTrattOS | `cost_history.value` | Same pattern; aggregations inside SQL with `numeric` casts |
| iguanatrader | `orders.quantity`, `orders.limit_price` | SQLAlchemy `Numeric(18, 8)` → Python `Decimal` |
| iguanatrader | `equity_snapshots.equity_usd` | Same; `Decimal` arithmetic in `BrokerService` |
| eligia-core | `whatsapp_invoice_lines.amount` | Ecto `:decimal` → `Decimal` struct in service |
