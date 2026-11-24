# HOME GENIES — W2 KYC and identity-data encryption: implementation and migration design (not built)

Date 2026-11-24 (Programme 02 autonomous cycle). Status: **design only — blocked by owner decision A-01 (key custody)**, with P0-05
(retention / deletion) and D-06 (who may verify / see) shaping parts of it. Nothing here invents a key-management policy: the design
isolates that choice behind one interface so the code does not change when A-01 is answered. Readiness reference:
`HOME_GENIES_PROGRAMME_02_READINESS.md` W2; findings: `HOME_GENIES_REPORTS_AND_EXPORTS_SECURITY_AUDIT_W4.md` §3 (field register).

## 1. What is stored in plaintext today (verified in code, 2026-11-24)
| Collection.field | Written by | Read in full by |
|---|---|---|
| `users.aadhaar_number` | registration (`auth_routes.py:294`), registration activation (`admin_routes.py:1076`), admin profile edit | nobody in full — every response masks (`core.mask_aadhaar`) |
| `registration_requests.aadhaar_number` | registration request (`auth_routes.py:230`) | nobody in full (admin list masks) |
| `kyc_records.pan`, `.aadhaar`, `.bank_account`, `.ifsc`, `.account_holder_name` | member KYC submit (`wallet_routes.py:123-126`), finance edit (`admin_routes.py`) | nobody in full (KYC list and member view mask) |
| `vendors.pan`, `.bank_account`, `.ifsc`, `.bank_account_name`; `vendors.onboarding.{business.pan, bank.account_number}` | onboarding (`vendor_onboarding.py:593-604`), bank-change approval | nobody in full (`_public_vendor`, onboarding view mask) |
| `vendor_change_requests.payload.bank_account` | vendor bank-change request (`governance_routes.py:198`) | nobody in full (masked lists) |
No code queries by any of these values (no lookup / uniqueness on PAN, Aadhaar or account number), so encryption needs **no blind
index** today. Every way out already masks (W4). The exposure is therefore at rest: database backups, database operators, anyone with
read access to the cluster.

## 2. Design
- **Library:** `cryptography` (AEAD, AES-256-GCM). Already pinned in the Emergent environment (`cryptography==50.0.0`); add the same pin to
  `backend/pyproject.toml` and `deploy/vercel-api/requirements.txt` (W6 rules: exact pin, audit).
- **Envelope encryption:** each value gets a random 96-bit nonce; the data key (DEK) encrypts values; the DEK is itself encrypted by a key
  encryption key (KEK) held per A-01. Stored form (replaces the plaintext field, same name, so readers fail closed if they forget to decrypt):
  `{"enc": "v1", "kid": "<key id>", "n": "<nonce b64>", "ct": "<ciphertext+tag b64>", "last4": "1234"}`.
  `last4` keeps every existing mask working without decryption (exposes exactly what responses show today).
  Associated data = `"<collection>:<field>:<record id>"`, so a ciphertext copied to another record or field does not decrypt.
- **One module, one interface** (`backend/pii_crypto.py`): `encrypt(value, context) -> dict`, `decrypt(doc, context) -> str`,
  `mask(doc) -> str`, `is_encrypted(v)`. Key access goes through a `KeyProvider` with `data_key(kid)` / `current_kid()`:
  - `EnvKeyProvider` — KEK from a hosting secret (e.g. `PII_KEK_BASE64`), for local tests only until A-01 says otherwise;
  - `KmsKeyProvider` — a managed KMS (AWS / GCP / other) if A-01 chooses it.
  Which one runs is a deployment setting decided by A-01; with no provider configured the application **refuses to write** a KYC record
  (fail closed, as the money guard does) rather than store plaintext.
- **Who may decrypt:** only code paths that need the full value — today none of the screens; payout execution (P03) and the finance KYC
  edit form if the owner decides finance may see full values (D-06 / D16-W4 style decision). Every decryption is audited (record id,
  field, purpose; never the value).
- **Key rotation:** new writes use `current_kid()`; a resumable sweep (`sweeps.run_sweep`) re-encrypts old `kid` records; both keys stay
  readable until the sweep completes. No downtime.

## 3. Migration (no production run without the owner — same gate as P1-01)
1. Verified backup and a restored copy (P1-01 procedure).
2. **Dry run** on the restored copy: counts per collection / field, already-encrypted count, malformed values (reported by record id,
   never by value).
3. **Apply** as a resumable, idempotent sweep per collection (skip already-encrypted values; checkpoint; per-record failure isolation;
   `job_runs` record). The application reads both forms during the migration (`is_encrypted` check).
4. **Verify**: decrypt-compare on the restored copy for every record before production; in production, a read-only report that no
   plaintext value remains (`$type: string` count = 0 per field).
5. Plaintext copies in backups age out only under the retention policy (P0-05) — encryption does not delete history.

## 4. Tests to add with the implementation
Round trip per field; wrong associated data refused; tampered ciphertext refused; unknown `kid` refused; masks unchanged in every
response (W4 suite); no plaintext in any API response, export, log or audit record; write refused when no key provider is configured;
migration dry run writes nothing; apply idempotent and resumable after interruption; rotation sweep; performance of list endpoints
(masking from `last4`, no decryption on list paths).

## 5. Decisions needed (owner)
| ID | Question | Blocks |
|---|---|---|
| A-01 | Where the key encryption key lives and who may rotate it (hosting secret store, managed KMS, other) | all of W2 (production) |
| P0-05 | How long identity data is kept and what "delete my account" removes | deletion / anonymisation, backup ageing |
| D-06 / D-16 | Whether any admin role may ever see a full PAN / Aadhaar / account number (today: nobody) | the decrypt-for-display path |
