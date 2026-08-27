# Drill 03 — Withdraw consent

**Objective:** prove you can find, read, and reverse the data-use switches —
and that "it looks off" and "it is off" are the same thing. ~7 min.

## Steps

1. Govern tab (`#/govern`) → set **Region** to *United States — opt-out
   style*. Watch the consent rows flip to *"not asked yet — region default:
   granted"* for the non-sensitive purposes.
2. Notice the honest label: nothing was stored about you; this is a
   *default*, and the UI says so instead of pretending you were asked.
3. **Withdraw** Personalization. Save a preference (a watchlist chip). It
   must fail with a classified CONSENT_REQUIRED error — an explicit
   withdrawal beats the regional default.
4. Switch Region back to your usual one. Confirm the withdrawal **still**
   blocks saving (ledger entries outlive region experiments).
5. Check the ledger hash-chain badge stays green.

## Expected honest behavior to recognize

- Region scopes *defaults only*; the ledger is supreme (v3.4 #9).
- `kyc_biometrics` never shows a region-default grant — sensitive biometrics
  are opt-in everywhere.
- Withdrawal is a new chain entry: the past grant stays provable; nothing is
  rewritten.
- The Compliance Index's consent component reflects an intact chain — it
  measures *integrity*, not how permissive your settings are.

## Pass condition (self-judged)

You can explain to a colleague why a US-region default grant is not consent,
and why a later withdrawal still stands after a region change.
