# Conservative AWS Prewarm Image Recipe

This recipe reduces PermeantOS real-runtime E2E bootstrap time without creating
always-on infrastructure. It prepares an optional AMI or container base with the
slow, generic dependencies already installed, then the normal runner still
provisions a disposable EC2 instance, copies the current repository snapshot,
runs the migration, collects artifacts, and cleans up.

The conservative v1 does **not** bake model weights into the image. Model
weights are large, change independently from the runtime stack, and should only
be baked into an image after a measured cost/latency tradeoff justifies the
extra snapshot storage.

## Cost Model

The default cost assumption is:

- no EC2 compute cost while the image is idle
- standard EBS snapshot storage for the written blocks behind the AMI
- normal EC2/GPU cost only while an E2E instance is running
- no Fast Snapshot Restore or provisioned volume initialization in v1

AWS notes that EBS snapshot storage is based on the amount of data stored, not
empty provisioned blocks; the first snapshot stores a full copy of written data
and later snapshots are incremental. AWS also charges Fast Snapshot Restore
separately per snapshot/AZ while it is enabled, so this recipe keeps it off.

Use the local estimator before retaining an image:

```bash
scripts/aws-prewarm-cost-estimate.py \
  --snapshot-gib 40 \
  --snapshot-rate 0.05 \
  --retained-days 30 \
  --pretty
```

Adjust `--snapshot-rate` for the target region from the AWS EBS pricing page.
For example, at `$0.05/GiB-month`, a 40 GiB snapshot retained for 30 days is
about `$2.00` of snapshot storage.

## What To Prewarm

Prewarm only slow, reusable runtime dependencies:

- OS package updates required by the current AWS runner.
- Python virtual environment tooling.
- Rust toolchain.
- `cargo build` dependencies for the repository snapshot shape.
- `vllm==0.23.0` and its Python dependencies.
- CUDA/NVIDIA userspace stack already present in the selected AWS deep-learning
  base AMI.

Do not prewarm:

- Per-run source continuation files.
- Temporary key pairs, security groups, SSH known-hosts files, or tunnels.
- Real prompts, private manifests, model outputs, or user data.
- Hugging Face credentials or other secrets.
- Model weights, unless a later measured tradeoff approves them.

## AMI Build Procedure

This is intentionally manual-first so the first pass is auditable and easy to
tear down.

1. Pick the same region/AZ family used by the runner, usually `us-east-1`.
2. Launch a temporary builder instance from the existing runner base AMI. Do
   not use `scripts/aws-real-runtime-e2e.sh run` as the builder launcher,
   because that script is intentionally end-to-end and will clean up its
   instance when the run finishes.

   ```bash
   aws ec2 run-instances \
     --region us-east-1 \
     --image-id ami-01011b868ec560823 \
     --instance-type g4dn.xlarge \
     --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":80,"VolumeType":"gp3","DeleteOnTermination":true}}]' \
     --tag-specifications 'ResourceType=instance,Tags=[{Key=Project,Value=permeant-os},{Key=Purpose,Value=prewarm-builder}]'
   ```

   It is also acceptable to launch the builder manually in the console, as long
   as the instance is tagged clearly and terminated afterward.

3. On the builder, run the dependency setup performed by
   `scripts/aws-real-runtime-e2e.sh`:

   ```bash
   sudo apt-get update
   sudo apt-get install -y python3.10-venv
   curl https://sh.rustup.rs -sSf | sh -s -- -y
   export PATH=/home/ubuntu/.cargo/bin:$PATH
   python3 -m venv /home/ubuntu/permeant-prewarm-venv
   . /home/ubuntu/permeant-prewarm-venv/bin/activate
   pip install -U pip setuptools wheel
   pip install ninja
   pip install vllm==0.23.0
   python - <<'PY'
   import vllm
   print(vllm.__version__)
   PY
   ```

4. Clear temporary package caches that do not help startup:

   ```bash
   sudo apt-get clean
   rm -rf ~/.cache/pip
   ```

5. Stop the builder instance.
6. Create an AMI from the stopped builder and tag it:

   ```bash
   aws ec2 create-image \
     --region us-east-1 \
     --instance-id i-xxxxxxxxxxxxxxxxx \
     --name permeantos-prewarm-v0-YYYYMMDD \
     --description "PermeantOS conservative prewarm image: Rust, vLLM, CUDA stack; no model weights" \
     --tag-specifications 'ResourceType=image,Tags=[{Key=Project,Value=permeant-os},{Key=Purpose,Value=prewarm-e2e},{Key=ContainsModelWeights,Value=false}]'
   ```

7. Wait for the AMI to become `available`.
8. Estimate retained snapshot cost from the AMI snapshot size before keeping it.
9. Terminate the builder instance.

## Runner Usage

Use the prewarmed AMI by overriding the runner AMI:

```bash
AWS_AMI_ID=ami-your-prewarmed-image \
scripts/aws-real-runtime-e2e.sh run
```

The runner should still copy the current committed repository snapshot to the
target. The AMI is only a dependency/cache accelerator; it is not the source of
truth for PermeantOS code.

## Container Variant

A container image can carry the same conservative prewarm payload if the target
environment already has a compatible NVIDIA driver/runtime:

- Base it on the CUDA/vLLM-compatible image family used by the target host.
- Install Python tooling, Rust, `ninja`, and `vllm==0.23.0`.
- Keep PermeantOS source, run artifacts, prompts, source continuation files,
  credentials, and model weights out of the image.
- Tag the image with `Project=permeant-os`, runtime stack version, and
  `ContainsModelWeights=false`.
- Document registry storage and transfer costs before retaining the image.

The current AWS E2E runner is AMI-oriented, so container execution is a future
runner integration path rather than the default v1 recipe.

## Validation

For a candidate prewarmed image:

1. Run one normal E2E cycle with `AWS_AMI_ID=ami-your-prewarmed-image`.
2. Confirm `fidelity-analysis.json` and `slot-probe-summary.json` are produced.
3. Compare setup time and total instance lifetime against a cold-image run.
4. Confirm no model weights or secrets are present in the AMI.
5. Confirm cleanup removed the E2E instance, key pair, security group, local
   PEM, and tunnel.

## Cleanup

When the prewarmed image is no longer needed:

1. Confirm no running instances still depend on it.
2. Deregister the AMI and delete associated snapshots:

   ```bash
   aws ec2 deregister-image \
     --region us-east-1 \
     --image-id ami-your-prewarmed-image \
     --delete-associated-snapshots
   ```

3. If snapshots remain because they are shared with another AMI, identify and
   delete only the snapshots that are safe to remove.

AWS documentation notes that deregistering an AMI does not terminate instances
launched from it and does not, by default, delete all associated snapshots.
Snapshots that remain after deregistration continue to incur storage costs.

## Source Notes

- AWS EBS pricing: <https://aws.amazon.com/ebs/pricing/>
- AWS EC2 AMI deregistration docs:
  <https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/deregister-ami.html>
- AWS EBS snapshot deletion docs:
  <https://docs.aws.amazon.com/ebs/latest/userguide/ebs-deleting-snapshot.html>
