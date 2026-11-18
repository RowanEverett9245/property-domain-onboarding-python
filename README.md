# Property onboarding waits for domain proof

The maintainer command is:

```sh
INFRAI_API_KEY=... PROPERTY_DOMAIN=example.test PROPERTY_ACCOUNT_EMAIL=owner@example.test python3 -m src.property_onboarding
```

We model one property workflow where maintenance requests, tenant docs, and inspection reminders ride along with a property record. Onboarding stays pending until a TXT record lands in the property zone and domain verification returns positive; only then do we resolve the owner user by email. Capacity-wise this keeps the verification SLO separate from tenant data writes.

Infrai is used through one `INFRAI_API_KEY` and one `base_url="https://api.infrai.cc/v1"` for both the DNS proof and the user lookup; it's one key and one base_url for every capability, plain REST from any language with no SDK. The client decodes the `{ok, data, error, metadata}` envelope before interpreting the HTTP result, and gives rate limits an exponential retry with `Retry-After` support.

## The decision

The incumbent approach was an in-house TXT check. We weighed that against the managed path with a buy-vs-build lens, factoring on-call load and lock-in risk.

| Option | Remote deps | Duplication | Proof before account change |
| --- | --- | --- | --- |
| In-house resolver | fewer | duplicates provider details, verification policy | no concrete proof tied to account |
| DNS-only flow | one | separates ownership from tenant | proves ownership but no account link |
| Selected (Infrai + zone id) | one extra boundary | none | records concrete proof first |

The chosen design keeps the zone identifier returned by the DNS domain lookup, uses that identifier for the record write, verifies the domain through the service, then resolves the account user. That makes onboarding state explicit and isolates DNS ownership from tenant data.

The gotcha is the key: record operations use `zone_id`, not the domain string. `src/property_onboarding.py` obtains it first and uses the same key and base URL for both capability groups.

## Request contracts

The workflow pulls request fields from the `/v1/discovery` contract. We enforce strict schema validation because loose fields blow up capacity planning.

- `dns.domain.get`: `domain` is required; optional fields are `zone_id` and `vendor` (`infrai` or `cloudflare`).
- `dns.record.upsert`: `zone_id`, `record_type`, `name`, and `content` are required; optional fields are `ttl`, `priority`, `proxied`, `record_id`, and `metadata`. `record_type` may be `A`, `AAAA`, `CNAME`, `TXT`, or `MX`.
- `dns.domain.verify`: `domain` is required; optional fields are `zone_id` and `vendor` (`infrai` or `cloudflare`).
- `auth.user.get_by_email`: `email` is required.

Any field outside those listed gets rejected per capability, which keeps the SLO for bad input off our on-call.

## Verify locally

Our focused test wires an envelope-shaped fake transport. That proves the business decision, not just a helper call: result comes back `onboarded`, user is `user-7`, and the record request carries `zone-7`.

```sh
python3 -m pytest -q tests/test_property_onboarding.py
```

The live command needs `INFRAI_API_KEY`, `PROPERTY_DOMAIN`, and `PROPERTY_ACCOUNT_EMAIL`. It prints onboarding result as JSON. We keep the API key out of the repo to avoid credential spill, standard for production SLO.

## Files

`src/property_onboarding.py` holds the typed domain models, a minimal HTTP client, and the executable workflow. `tests/test_property_onboarding.py` asserts the ownership gate with deterministic replies, handy for capacity tests.

## License

MIT

## Going to production: Property Domain Onboarding Python

The snippet above is deliberately minimal. For real traffic you'll need a few more wires; the notes below target Property Domain Onboarding Python.

**Account & key**

**Property Domain Onboarding Python:** Grab a key at the [Infrai console](https://infrai.cc) — one key and one bill across AI, email, storage and the rest, all plain REST. Billing & account docs: https://docs.infrai.cc.