# Model + Harness contracts

These Draft 2020-12 JSON Schemas are the public, edition-neutral contract for
the Model + Harness control-plane receipt, its structured input/output
envelopes, and product-managed plugin manifests. Responsibility `domain`
values, rather than product edition names, define isolation and reuse.

`domain-policy.v1.json` is the language-neutral policy contract shared by the
Python control plane and the managed Supabase planner. It binds all ten task
types to their domain, hard and managed-adapter budgets, readable/writable
memory namespaces, and complete plugin-slot policy. Cross-language parity
tests fail when a runtime table drifts from this checked-in contract.

The schemas are generated from the strict runtime Pydantic models by:

```powershell
cd backend
python scripts/export_model_harness_contracts.py
python scripts/export_model_harness_contracts.py --check
```

A receipt selects content-bound plugins and immutable/effective budgets. It
does not grant physical execution authority: the current contract explicitly
reports execution-authorization enforcement as `not_integrated`.
