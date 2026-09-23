# Real API Canary Execution Plan

- Provider: `mock`
- Model: `mock-commit-message-generator`
- Sample count: `20`
- Planned request count: `65`
- Strategy distribution: `{'G0': 20, 'G1': 20, 'G4': 20, 'G5': 5}`
- Estimated input tokens: `0`
- Estimated output tokens: `4160`
- Estimated cost: `not_available`
- Cost status: `requires_manual_provider_pricing`

## Go / No-Go Criteria

- dataset leakage gate passed
- exemplar leakage gate passed
- planned_request_count = 65
- G5 only runs on synthetic_multi
- prompt rendering completed
- no unexpected truncation
- cache works
- resume works
- evaluation schema works
- API key absent from logs and metadata

This Canary validates protocol and runtime stability only. It is not evidence for paper-level generation quality.
