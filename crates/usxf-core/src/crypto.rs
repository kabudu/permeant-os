use aes_gcm::aead::{Aead, KeyInit};
use aes_gcm::{Aes256Gcm, Key, Nonce};
use anyhow::{bail, Context, Result};
pub use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};
use serde::{Deserialize, Serialize};

const AES_GCM_NONCE_LEN: usize = 12;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EncryptedEnvelope {
    pub ciphertext: Vec<u8>,
    pub nonce: Vec<u8>,
    pub signature: Vec<u8>,  // Ed25519 signature
    pub public_key: Vec<u8>, // Sender public key
}

/// Encrypts plaintext data using AES-256-GCM and signs the ciphertext with Ed25519 (Encrypt-then-Sign).
pub fn seal_packet(
    plaintext: &[u8],
    aes_key: &[u8; 32],
    signing_key: &SigningKey,
) -> Result<EncryptedEnvelope> {
    // 1. Encrypt using AES-256-GCM
    let key = Key::<Aes256Gcm>::from_slice(aes_key);
    let cipher = Aes256Gcm::new(key);

    // Generate a secure 96-bit nonce
    let mut nonce_bytes = [0u8; AES_GCM_NONCE_LEN];
    use rand::RngCore;
    rand::thread_rng().fill_bytes(&mut nonce_bytes);
    let nonce = Nonce::from_slice(&nonce_bytes);

    let ciphertext = cipher
        .encrypt(nonce, plaintext)
        .map_err(|e| anyhow::anyhow!("Encryption failed: {:?}", e))?;

    // 2. Sign the ciphertext + nonce using Ed25519 (to protect both)
    let mut signed_payload = Vec::with_capacity(ciphertext.len() + nonce_bytes.len());
    signed_payload.extend_from_slice(&ciphertext);
    signed_payload.extend_from_slice(&nonce_bytes);

    let signature = signing_key.sign(&signed_payload);

    Ok(EncryptedEnvelope {
        ciphertext,
        nonce: nonce_bytes.to_vec(),
        signature: signature.to_bytes().to_vec(),
        public_key: signing_key.verifying_key().to_bytes().to_vec(),
    })
}

/// Verifies the signature of the ciphertext, then decrypts it using AES-256-GCM.
pub fn open_packet(envelope: &EncryptedEnvelope, aes_key: &[u8; 32]) -> Result<Vec<u8>> {
    if envelope.nonce.len() != AES_GCM_NONCE_LEN {
        bail!(
            "Invalid nonce length: expected {}, got {}",
            AES_GCM_NONCE_LEN,
            envelope.nonce.len()
        );
    }

    // 1. Verify the public key and signature
    let public_key = VerifyingKey::from_bytes(
        &envelope
            .public_key
            .clone()
            .try_into()
            .map_err(|_| anyhow::anyhow!("Invalid public key length"))?,
    )
    .context("Failed to parse verifying key")?;

    let signature_bytes: [u8; 64] = envelope
        .signature
        .clone()
        .try_into()
        .map_err(|_| anyhow::anyhow!("Invalid signature length"))?;
    let signature = Signature::from_bytes(&signature_bytes);

    let mut signed_payload = Vec::with_capacity(envelope.ciphertext.len() + envelope.nonce.len());
    signed_payload.extend_from_slice(&envelope.ciphertext);
    signed_payload.extend_from_slice(&envelope.nonce);

    public_key
        .verify(&signed_payload, &signature)
        .context("Signature verification failed (integrity check failed)")?;

    // 2. Decrypt
    let key = Key::<Aes256Gcm>::from_slice(aes_key);
    let cipher = Aes256Gcm::new(key);
    let nonce = Nonce::from_slice(&envelope.nonce);

    let plaintext = cipher
        .decrypt(nonce, envelope.ciphertext.as_slice())
        .map_err(|e| anyhow::anyhow!("Decryption failed (ciphertext may be corrupted): {:?}", e))?;

    Ok(plaintext)
}
