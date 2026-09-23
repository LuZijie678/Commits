# MICA-v3 Data Card

## Assets

- Step1 high-confidence k=1
- Step2 strict synthetic k1/k2
- Step2 Step3-ready synthetic
- hard_b train/dev/test
- M weak train/dev/final-test
- M-align-calib
- RealDomainBinary test
- renderer data, optional

## Supervision Reliability

- `high`
- `medium-high`
- `medium`
- `medium-low`
- `eval-only`

## Usage Boundaries

- M-final-test = eval-only
- hard_b-test = eval-only
- RealDomainBinary-test = eval-only
- M weak = censored k>=2 only
- M-align-calib = small real alignment calibration/eval only
- intent_subjects/messages = renderer only, not attribution matching
