# Objective 2 Protocol: Model Development

**Research objective:** Develop and evaluate a unified differentiable sequence–ensemble architecture.

**Chapter 3 phase:** Phase 2, model development and comparative evaluation.

## Candidate architecture

20-day by 13-feature sequence → bidirectional LSTM → temporal attention → differentiable tree head → binary output.

## Required comparisons

- Bi-LSTM baseline.
- Attention–linear baseline.
- Differentiable tree-head model.
- Same-information comparisons using identical 20 × 13 inputs.
- Structured-feature baselines must be identified as different-information comparisons.

## Teacher anchoring

The teacher is used during training only. The student must run independently at inference.

## Evaluation

Use PR-AUC as the primary metric and report thresholded metrics, calibration, and latency. State whether each result is development, train/validation, frozen-comparator test evidence, or final-student independent test evidence.
