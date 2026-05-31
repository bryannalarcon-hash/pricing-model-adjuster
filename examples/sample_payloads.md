# Dashboard test payloads

Copy any single JSON object below into the **Predict** panel's editor and hit Predict.
The "expect" note says what the result should demonstrate. For the **Batch** panel, upload
`examples/sample_bookings.csv`.

---

### 1. Plumbing — small, well-scoped (with original estimate)
_Expect: tight interval, moderate-to-high confidence._
```json
{"job_id":"demo-plumb-01","service_category":"Plumbing","zip_code":"33484","job_description":"Replace kitchen sink shutoff valve, I supply the valve","original_estimate":150,"deadline":"As soon as possible","booking_month":"2026-04"}
```

### 2. Plumbing — water heater (the bundled sample)
_Expect: larger estimate, correction applied to the original._
```json
{"job_id":"demo-plumb-02","service_category":"Plumbing","service_subtype":"Water Heater Replacement","zip_code":"78704","job_description":"50-gallon gas water heater stopped working, pilot light won't stay lit. Need replacement.","original_estimate":1850,"deadline":"Within 1-2 weeks","booking_month":"2026-05"}
```

### 3. Cleaning — NO original estimate
_Expect: still returns an estimate (model anchors on the category median)._
```json
{"job_id":"demo-clean-01","service_category":"Cleaning","zip_code":"75062","job_description":"Exterior window wash, 2-story home, about 20 windows","deadline":"I'm flexible"}
```

### 4. HVAC — furnace
_Expect: production category, normal confidence._
```json
{"job_id":"demo-hvac-01","service_category":"HVAC","zip_code":"33324","job_description":"Furnace not heating, blower runs but no warm air. Likely a bad igniter.","original_estimate":420}
```

### 5. OOD — large job (> $5k)
_Expect: LOW confidence + amber banner (ood_midpoint: estimate above $5,000)._
```json
{"job_id":"demo-ood-big","service_category":"General Contractor","zip_code":"33463","job_description":"Full kitchen remodel: new cabinets, quartz countertops, flooring, and partial rewiring","original_estimate":12000}
```

### 6. OOD — out-of-production category
_Expect: LOW confidence (Roofing is outside the 10 production verticals → ood_category)._
```json
{"job_id":"demo-ood-cat","service_category":"Roofing","zip_code":"33484","job_description":"Repair a small roof leak around a vent boot, a few shingles","original_estimate":800}
```

### 7. OOD — novel/gibberish description
_Expect: LOW confidence (job is unlike anything in training → ood_novelty)._
```json
{"job_id":"demo-novel","service_category":"Plumbing","zip_code":"78704","job_description":"asdf qwerty lorem ipsum random nonsense not a real job xyzzy","original_estimate":300}
```

### 8. Ambiguous / wide scope
_Expect: wider interval (scope ambiguous from the description)._
```json
{"job_id":"demo-wide","service_category":"Handyman","zip_code":"33484","job_description":"Various small repairs around the house, not totally sure what all is needed yet","original_estimate":250}
```

### 9. Electrical — panel upgrade
```json
{"job_id":"demo-elec-01","service_category":"Electrical","zip_code":"33324","job_description":"Upgrade main electrical panel from 100A to 200A service","original_estimate":2200}
```

### 10. Auto — out of production
_Expect: LOW confidence (ood_category)._
```json
{"job_id":"demo-auto","service_category":"Auto","zip_code":"75062","job_description":"Mobile mechanic to replace front brake pads and rotors","original_estimate":450}
```

---

### Malformed JSON (to test error handling)
_Expect: inline error in the editor, NO request sent._
```
{"job_id":"oops", "service_category": "Plumbing", zip_code: 78704
```

### Missing required field (valid JSON, server 400)
_Expect: error toast "zip_code required"._
```json
{"job_id":"demo-bad","service_category":"Plumbing","job_description":"missing the zip code"}
```
