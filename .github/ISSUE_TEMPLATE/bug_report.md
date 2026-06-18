---
name: Bug report
description: Report a reproducible PermeantOS bug
title: "bug: "
labels: [bug]
body:
  - type: markdown
    attributes:
      value: |
        Thanks for helping improve PermeantOS. Please do not include secrets, private prompts, cloud credentials, or sensitive migration manifests.
  - type: textarea
    id: summary
    attributes:
      label: Summary
      description: What went wrong?
    validations:
      required: true
  - type: textarea
    id: reproduce
    attributes:
      label: Reproduction steps
      description: Include commands, runtime versions, model, source/target hosts, and relevant environment variables.
      placeholder: |
        1. ...
        2. ...
        3. ...
    validations:
      required: true
  - type: textarea
    id: expected
    attributes:
      label: Expected behavior
    validations:
      required: true
  - type: textarea
    id: actual
    attributes:
      label: Actual behavior
    validations:
      required: true
  - type: textarea
    id: environment
    attributes:
      label: Environment
      placeholder: |
        OS:
        Rust version:
        Python version:
        Runtime adapter:
        Model:
        Cloud/provider, if relevant:
    validations:
      required: false
  - type: textarea
    id: artifacts
    attributes:
      label: Logs or manifests
      description: Redact sensitive content before sharing.
    validations:
      required: false
