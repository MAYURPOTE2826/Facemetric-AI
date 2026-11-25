# Try-on provider privacy - what was found, and why it stays UNVERIFIED

**Status for this deployment: `PROVIDER POLICY UNVERIFIED`** (the warning stays in the consent UI; it was not weakened).

Retrieved 2026-11-05 with a web-fetch tool and a web search. The tool summarises pages, so the wording below is a paraphrase / short extract of
what the tool returned, **not a certified copy**: read the linked pages yourself before relying on any line. Provider documentation changes.
Even a correct reading would not verify *this* deployment, because the terms differ by plan and by account settings, and I do not know which
plan or settings your `FAL_KEY` / `GEMINI_API_KEY` use.

## Google - Gemini API (used when `TRYON_PROVIDER=gemini`)
Source: Gemini API Additional Terms of Service (`https://ai.google.dev/gemini-api/terms`, redirects to `https://aistudio.google.com/docs/terms`).
| Topic | What the page says (as returned) |
|---|---|
| Unpaid services | content submitted and generated responses are used to "provide, improve, and develop" Google products and machine-learning technologies; "human reviewers may read, annotate, and process your API input and output" |
| Paid services | "Google doesn't use your prompts ... or responses to improve our products" |
| Retention | unpaid: no period stated on the page; paid: prompts and responses logged "for a limited period of time" (no duration stated), "solely for detecting and preventing violations" of the Prohibited Use Policy; may be "stored transiently or cached in any country in which Google or its agents maintain facilities"; grounding features: stored 30 days |
| What counts as "paid" | per the page, API access through a Cloud project with an active billing account (AI Studio access counts if the account has one, or is a Workspace enterprise account) |
**Consequence:** if the key behind `GEMINI_API_KEY` is on an unpaid/free tier, user photographs sent for try-on may be used to improve Google
products and read by human reviewers. That would contradict the comfort of the consent text and is the single most important thing to check.
Status: **UNVERIFIED** (plan unknown).

## fal.ai (used when `TRYON_PROVIDER=fal`, the default if `FAL_KEY` is set)
Sources: Privacy Policy (`https://fal.ai/privacy`, also `https://fal.ai/legal/privacy-policy`); Model APIs docs: Data Retention & Storage
(`https://fal.ai/docs/documentation/model-apis/media-expiration`), FAQ (`https://fal.ai/docs/documentation/model-apis/faq`), Platform Headers
(`https://fal.ai/docs/documentation/model-apis/common-parameters`).
| Topic | What was found |
|---|---|
| Privacy policy | collects "your prompts and other content you choose to upload"; does **not** state how long API inputs/outputs are kept, and does **not** say whether they are used to train models; refers to a separate media-expiration document; names no sub-processors |
| Request payloads | documentation summary: request inputs and outputs stored by the platform for **90 days by default**; a per-request header `X-Fal-Store-IO: 0` is said to stop JSON payload storage |
| Uploaded / generated files | stored on fal's CDN under media-expiration controls; one page says generated media is available "at least 7 days" by default, another says the account default is "forever" and publicly readable if not configured - **the pages disagree** |
| Public access | media URLs returned by fal are described as **publicly accessible** to anyone holding the URL until expiry (ACLs can restrict this) |
| Training | no statement about training on Model-API uploads was found; the only explicit "not used to train" statement found was for a different product (fal's Agent chat) |
Status: **UNVERIFIED**. Open questions for fal (ask in writing): is API-uploaded media used for training or evaluation? what is the default
retention for your account? are returned URLs public by default and can they be made private?

## What Alexandra itself does (verified from the code and tests)
Sends one cropped front-face photo (<= 768 px) plus a text prompt; stores the generated image inside the encrypted report; keeps no second copy of
the photo for this; records only `{version, provider, granted_at, expires_at}` as consent. It does **not** currently send any of the retention-minimising
headers mentioned above, because their exact accepted values could not be tested against the live service and a malformed header could break
generation; adding them is a candidate experiment once a test account is available. **No claim is made that retention is reduced.**

## What would close this gate
1. Decide the plan/tier you will use for each provider and confirm it in the provider's dashboard or contract (paid Gemini billing; fal account terms).
2. Obtain written confirmation (or a data-processing agreement) covering: no training on submitted media, retention period, public-URL behaviour,
   location of processing.
3. Update the consent text only with statements that confirmation supports; until then keep `PROVIDER POLICY UNVERIFIED` visible, or disable try-on.
