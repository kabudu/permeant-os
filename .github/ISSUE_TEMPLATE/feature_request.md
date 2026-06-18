---
name: Feature request
description: Propose a feature or roadmap item
title: "feature: "
labels: [enhancement]
body:
  - type: textarea
    id: problem
    attributes:
      label: Problem or opportunity
      description: What should PermeantOS support, improve, or clarify?
    validations:
      required: true
  - type: textarea
    id: proposal
    attributes:
      label: Proposed solution
    validations:
      required: true
  - type: textarea
    id: alternatives
    attributes:
      label: Alternatives considered
    validations:
      required: false
  - type: dropdown
    id: area
    attributes:
      label: Area
      options:
        - Core protocol / Rust daemon
        - Runtime adapter
        - Manifest / analyzer
        - Agent Memory Graph
        - Cloud validation
        - Documentation
        - Security
        - Other
    validations:
      required: true
