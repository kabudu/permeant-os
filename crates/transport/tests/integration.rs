use chrono::Utc;
use permeant_transport::{
    compute_crc32, decode_binary_frame, default_transport_candidates, encode_binary_frame,
    negotiate_transport, recv_binary_frame, recv_message, send_binary_frame, send_message,
    verify_chunk_crc32, AgentGraphBinding, AgentGraphBindingKvSpan, BinaryFrame,
    BinaryFrameValidator, EndpointRole, MigrationMessage, PayloadCodecMetadata,
    ProductionTransportMode, ProductionTransportProfile, SecureSessionHello,
    SecureSessionHelloRequest, TransportCandidate,
};
use std::collections::HashMap;
use tokio::io::AsyncWriteExt;
use tokio::net::{TcpListener, TcpStream};
use usxf_core::crypto::{open_packet, seal_packet, SigningKey};
use usxf_core::{AttentionType, ExchangeDtype, ModelCacheSpec, ModelIdentity, UsxfHeader};

#[tokio::test]
async fn test_tcp_handshake_and_exchange() {
    // 1. Start a local mock server on a random port
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let local_addr = listener.local_addr().unwrap();

    // Spawn server in a background tokio task
    let server_handle = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();

        // Step A: Recv CapabilityRequest
        let cap_req = recv_message(&mut socket).await.unwrap();
        if let MigrationMessage::CapabilityRequest {
            model_architecture, ..
        } = cap_req
        {
            assert_eq!(model_architecture, "Llama-3.1-8B-Mock");

            // Accept it
            send_message(
                &mut socket,
                &MigrationMessage::CapabilityResponse {
                    accepted: true,
                    error_message: None,
                    target_device: "Metal/Mock".to_string(),
                },
            )
            .await
            .unwrap();
        } else {
            panic!("Expected CapabilityRequest");
        }

        // Step B: Recv HeaderEnvelope
        let msg = recv_message(&mut socket).await.unwrap();
        if let MigrationMessage::HeaderEnvelope(envelope) = msg {
            let aes_key = [5u8; 32];
            let plaintext = open_packet(&envelope, &aes_key).unwrap();
            let header: UsxfHeader = serde_json::from_slice(&plaintext).unwrap();
            assert_eq!(header.seq_len, 123);

            send_message(&mut socket, &MigrationMessage::HeaderAck { accepted: true })
                .await
                .unwrap();
        } else {
            panic!("Expected HeaderEnvelope");
        }
    });

    // 2. Client connection
    let mut client_socket = TcpStream::connect(local_addr).await.unwrap();

    // Send CapabilityRequest
    send_message(
        &mut client_socket,
        &MigrationMessage::CapabilityRequest {
            model_architecture: "Llama-3.1-8B-Mock".to_string(),
            attention_type: "gqa".to_string(),
            seq_len: 123,
        },
    )
    .await
    .unwrap();

    // Recv CapabilityResponse
    let resp = recv_message(&mut client_socket).await.unwrap();
    if let MigrationMessage::CapabilityResponse {
        accepted,
        target_device,
        ..
    } = resp
    {
        assert!(accepted);
        assert_eq!(target_device, "Metal/Mock");
    } else {
        panic!("Expected CapabilityResponse");
    }

    // Send Header
    let dummy_tokens = vec![42u32; 123];
    let block_hashes = usxf_core::validation::compute_token_block_hashes(&dummy_tokens, 256);
    let header = UsxfHeader {
        usxf_version: "1.1".to_string(),
        model_architecture: "Llama-3.1-8B-Mock".to_string(),
        model_identity: ModelIdentity {
            config_hash: "sha256:7f8e9a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f"
                .to_string(),
            weights_revision: "hf:mock/Llama-3.1-8B-Mock".to_string(),
        },
        attention_type: AttentionType::Gqa,
        model_cache_spec: ModelCacheSpec {
            n_layers: 4,
            n_q_heads: 8,
            n_kv_heads: 2,
            head_dim: 64,
            hidden_size: 1024,
            max_position_embeddings: Some(131072),
            rope_theta: Some(500000.0),
            sliding_window: None,
        },
        mla_spec: None,
        chat_state: None,
        token_ids: dummy_tokens,
        seq_len: 123,
        batch_size: 1,
        dtype: ExchangeDtype::Float32,
        source_quantization: None,
        transfer_quantization: None,
        block_size: 256,
        block_hashes,
        position_ids: None,
        extra: HashMap::new(),
        created_at: Utc::now(),
        extractor_id: "extractor".to_string(),
        checksum: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
            .to_string(),
        signature: "".to_string(),
    };

    let aes_key = [5u8; 32];
    let mut csprng = rand::rngs::OsRng;
    let signing_key = SigningKey::generate(&mut csprng);
    let serialized_header = serde_json::to_vec(&header).unwrap();
    let envelope = seal_packet(&serialized_header, &aes_key, &signing_key).unwrap();

    send_message(
        &mut client_socket,
        &MigrationMessage::HeaderEnvelope(envelope),
    )
    .await
    .unwrap();

    let ack = recv_message(&mut client_socket).await.unwrap();
    if let MigrationMessage::HeaderAck { accepted } = ack {
        assert!(accepted);
    } else {
        panic!("Expected HeaderAck");
    }

    server_handle.await.unwrap();
}

#[tokio::test]
async fn test_binary_frame_socket_roundtrip() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let local_addr = listener.local_addr().unwrap();

    let server_handle = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let frame = recv_binary_frame(&mut socket, 1024).await.unwrap();
        assert_eq!(frame.stream_id, 11);
        assert_eq!(frame.frame_index, 3);
        assert_eq!(frame.payload, b"binary-stream".to_vec());
        send_binary_frame(
            &mut socket,
            &BinaryFrame::new(2, 12, 1, b"ack".to_vec()),
            1024,
        )
        .await
        .unwrap();
    });

    let mut client_socket = TcpStream::connect(local_addr).await.unwrap();
    send_binary_frame(
        &mut client_socket,
        &BinaryFrame::new(1, 11, 3, b"binary-stream".to_vec()),
        1024,
    )
    .await
    .unwrap();
    let ack = recv_binary_frame(&mut client_socket, 1024).await.unwrap();
    assert_eq!(ack.stream_id, 12);
    assert_eq!(ack.payload, b"ack".to_vec());

    server_handle.await.unwrap();
}

#[test]
fn test_secure_session_hello_verifies_signed_profile() {
    let mut csprng = rand::rngs::OsRng;
    let signing_key = SigningKey::generate(&mut csprng);
    let hello = SecureSessionHello::signed(
        SecureSessionHelloRequest {
            session_id: "session:test".to_string(),
            role: EndpointRole::Source,
            node_id: "source-node".to_string(),
            peer_node_id: Some("target-node".to_string()),
            profile: ProductionTransportProfile::websocket_mtls_binary(),
            nonce: vec![7u8; 32],
            supported_codecs: vec!["raw".to_string(), "qatq".to_string()],
        },
        &signing_key,
    )
    .unwrap();

    hello.verify().unwrap();
}

#[test]
fn test_secure_session_hello_rejects_tampering() {
    let mut csprng = rand::rngs::OsRng;
    let signing_key = SigningKey::generate(&mut csprng);
    let mut hello = SecureSessionHello::signed(
        SecureSessionHelloRequest {
            session_id: "session:test".to_string(),
            role: EndpointRole::Target,
            node_id: "target-node".to_string(),
            peer_node_id: Some("source-node".to_string()),
            profile: ProductionTransportProfile::websocket_mtls_binary(),
            nonce: vec![8u8; 32],
            supported_codecs: vec!["raw".to_string()],
        },
        &signing_key,
    )
    .unwrap();

    hello.node_id = "different-target".to_string();

    assert!(hello.verify().is_err());
}

#[test]
fn test_transport_negotiation_prefers_portable_secure_baseline() {
    let source = default_transport_candidates();
    let target = default_transport_candidates();

    let result = negotiate_transport(&source, &target).unwrap();

    assert_eq!(result.selected.mode, ProductionTransportMode::WebSocketMtls);
    assert!(result.selected.require_mutual_tls);
    assert!(result.selected.binary_framing);
}

#[test]
fn test_transport_negotiation_falls_back_to_safe_tcp_mtls() {
    let source = default_transport_candidates();
    let target = vec![TransportCandidate {
        profile: ProductionTransportProfile::framed_tcp_mtls_binary(),
        priority: 50,
        reason: "target supports only compatibility mode".to_string(),
    }];

    let result = negotiate_transport(&source, &target).unwrap();

    assert_eq!(result.selected.mode, ProductionTransportMode::FramedTcpMtls);
    assert_eq!(result.selected.max_frame_bytes, 16 * 1024 * 1024);
}

#[test]
fn test_transport_negotiation_rejects_insecure_downgrade() {
    let source = default_transport_candidates();
    let mut insecure_profile = ProductionTransportProfile::websocket_mtls_binary();
    insecure_profile.require_mutual_tls = false;
    let target = vec![TransportCandidate {
        profile: insecure_profile,
        priority: 100,
        reason: "target tried to disable mTLS".to_string(),
    }];

    let error = negotiate_transport(&source, &target)
        .unwrap_err()
        .to_string();

    assert!(error.contains("no mutually supported production transport candidate"));
}

#[test]
fn test_binary_frame_roundtrip_and_replay_rejection() {
    let frame = BinaryFrame::new(42, 7, 1, b"payload".to_vec());
    let encoded = encode_binary_frame(&frame, 1024).unwrap();
    let decoded = decode_binary_frame(&encoded, 1024).unwrap();
    assert_eq!(decoded, frame);

    let mut validator = BinaryFrameValidator::new(1024);
    validator.accept(&decoded).unwrap();
    let duplicate = validator.accept(&decoded).unwrap_err().to_string();
    assert!(duplicate.contains("duplicate binary frame rejected"));

    let next_frame = BinaryFrame::new(42, 7, 2, b"payload-2".to_vec());
    validator.accept(&next_frame).unwrap();
    let reverse_stream_frame = BinaryFrame::new(42, 8, 1, b"reverse".to_vec());
    validator.accept(&reverse_stream_frame).unwrap();
}

#[test]
fn test_binary_frame_rejects_crc_and_size_failures() {
    let frame = BinaryFrame::new(1, 1, 1, b"payload".to_vec());
    let mut encoded = encode_binary_frame(&frame, 1024).unwrap();
    let last = encoded.len() - 1;
    encoded[last] ^= 0xff;
    let crc_error = decode_binary_frame(&encoded, 1024).unwrap_err().to_string();
    assert!(crc_error.contains("CRC32 mismatch"));

    let oversize = BinaryFrame::new(1, 1, 2, vec![0u8; 8]);
    let encode_error = encode_binary_frame(&oversize, 4).unwrap_err().to_string();
    assert!(encode_error.contains("exceeds configured maximum"));
}

#[tokio::test]
async fn test_crc32_corruption_handling() {
    let raw_payload = vec![1u8, 2, 3, 4, 5];
    let correct_crc = compute_crc32(&raw_payload);

    let valid_chunk = MigrationMessage::PayloadChunk {
        chunk_index: 0,
        layer_index: 0,
        tensor_name: "layer.0.key".to_string(),
        codec: None,
        data: raw_payload.clone(),
        crc32: correct_crc,
    };

    // Verify valid chunk passes
    assert!(verify_chunk_crc32(&valid_chunk).unwrap());

    let corrupted_chunk = MigrationMessage::PayloadChunk {
        chunk_index: 0,
        layer_index: 0,
        tensor_name: "layer.0.key".to_string(),
        codec: None,
        data: raw_payload.clone(),
        crc32: correct_crc ^ 1234, // modify CRC32
    };

    // Verify corrupted chunk fails
    assert!(!verify_chunk_crc32(&corrupted_chunk).unwrap());
}

#[tokio::test]
async fn test_payload_chunk_preserves_codec_metadata() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let local_addr = listener.local_addr().unwrap();

    let server_handle = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let chunk = recv_message(&mut socket).await.unwrap();
        let MigrationMessage::PayloadChunk {
            codec, data, crc32, ..
        } = chunk
        else {
            panic!("Expected PayloadChunk");
        };
        assert_eq!(data, vec![9, 8, 7, 6]);
        assert_eq!(crc32, compute_crc32(&data));
        let codec = codec.expect("codec metadata");
        assert_eq!(codec.transfer_codec, "qatq");
        assert_eq!(codec.storage, "qatq-phase2");
        assert_eq!(codec.strategy.as_deref(), Some("byte-plane-blocks"));
        assert_eq!(codec.raw_f32le_len, 16);
    });

    let mut client_socket = TcpStream::connect(local_addr).await.unwrap();
    let data = vec![9, 8, 7, 6];
    send_message(
        &mut client_socket,
        &MigrationMessage::PayloadChunk {
            chunk_index: 0,
            layer_index: 0,
            tensor_name: "layer.0.key".to_string(),
            codec: Some(PayloadCodecMetadata {
                transfer_codec: "qatq".to_string(),
                storage: "qatq-phase2".to_string(),
                strategy: Some("byte-plane-blocks".to_string()),
                raw_f32le_len: 16,
            }),
            crc32: compute_crc32(&data),
            data,
        },
    )
    .await
    .unwrap();

    server_handle.await.unwrap();
}

#[tokio::test]
async fn test_protocol_abort_mid_stream() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let local_addr = listener.local_addr().unwrap();

    // Spawn server that expects CapabilityRequest then closed socket
    let server_handle = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let cap_req = recv_message(&mut socket).await.unwrap();
        assert!(matches!(
            cap_req,
            MigrationMessage::CapabilityRequest { .. }
        ));

        // Wait for next message which will fail because client abruptly disconnects
        let next_msg = recv_message(&mut socket).await;
        assert!(
            next_msg.is_err(),
            "Expected connection error on abrupt close"
        );
    });

    let mut client_socket = TcpStream::connect(local_addr).await.unwrap();
    send_message(
        &mut client_socket,
        &MigrationMessage::CapabilityRequest {
            model_architecture: "Llama-3.1-8B-Mock".to_string(),
            attention_type: "gqa".to_string(),
            seq_len: 100,
        },
    )
    .await
    .unwrap();

    // Drop socket to simulate abrupt crash / timeout
    drop(client_socket);

    server_handle.await.unwrap();
}

#[tokio::test]
async fn test_interrupted_agent_graph_binding_frame_fails_cleanly() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let local_addr = listener.local_addr().unwrap();

    let server_handle = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let result = recv_message(&mut socket).await;
        assert!(result.is_err(), "expected truncated graph frame to fail");
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("Failed to read frame content"));
    });

    let mut client_socket = TcpStream::connect(local_addr).await.unwrap();
    let payload =
        br#"{"AgentGraphBinding":{"manifest_path":"manifest.json","graph_path":"graph.json"}}"#;
    let declared_len = (payload.len() + 1) as u32;
    client_socket
        .write_all(&declared_len.to_be_bytes())
        .await
        .unwrap();
    client_socket.write_all(&[0]).await.unwrap();
    client_socket
        .write_all(&payload[..payload.len() / 2])
        .await
        .unwrap();
    drop(client_socket);

    server_handle.await.unwrap();
}

#[tokio::test]
async fn test_interrupted_payload_chunk_frame_fails_cleanly() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let local_addr = listener.local_addr().unwrap();

    let server_handle = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let result = recv_message(&mut socket).await;
        assert!(result.is_err(), "expected truncated payload frame to fail");
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("Failed to read frame content"));
    });

    let mut client_socket = TcpStream::connect(local_addr).await.unwrap();
    let tensor_name = b"layer.0.key";
    let declared_len = (1 + 4 + 4 + 4 + tensor_name.len() + 4 + 4 + 64) as u32;
    client_socket
        .write_all(&declared_len.to_be_bytes())
        .await
        .unwrap();
    client_socket.write_all(&[1]).await.unwrap();
    client_socket.write_all(&0u32.to_be_bytes()).await.unwrap();
    client_socket.write_all(&0u32.to_be_bytes()).await.unwrap();
    client_socket
        .write_all(&(tensor_name.len() as u32).to_be_bytes())
        .await
        .unwrap();
    client_socket.write_all(tensor_name).await.unwrap();
    drop(client_socket);

    server_handle.await.unwrap();
}

#[tokio::test]
async fn test_agent_graph_binding_roundtrip() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let local_addr = listener.local_addr().unwrap();
    let expected = AgentGraphBinding {
        manifest_path: "manifest.json".to_string(),
        graph_path: "graph.json".to_string(),
        graph_hash: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            .to_string(),
        prompt_byte_hash: Some(
            "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb".to_string(),
        ),
        prompt_token_hash: Some(
            "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc".to_string(),
        ),
        tokenizer_hash: Some(
            "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd".to_string(),
        ),
        kv_hash: Some(
            "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee".to_string(),
        ),
        kv_spans: vec![AgentGraphBindingKvSpan {
            node_id: "checkpoint:prompt".to_string(),
            token_start: 0,
            token_end: 8,
            cache_ref: "kv:prefix:0".to_string(),
            tokenizer_hash: Some(
                "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
                    .to_string(),
            ),
            block_hashes: vec![
                "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
                    .to_string(),
            ],
        }],
        artifacts: vec![],
    };
    let server_expected = expected.clone();

    let server_handle = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let message = recv_message(&mut socket).await.unwrap();
        assert!(matches!(
            message,
            MigrationMessage::AgentGraphBinding(binding) if binding == server_expected
        ));
        send_message(
            &mut socket,
            &MigrationMessage::AgentGraphBindingAck {
                accepted: true,
                error_message: None,
            },
        )
        .await
        .unwrap();
    });

    let mut client_socket = TcpStream::connect(local_addr).await.unwrap();
    send_message(
        &mut client_socket,
        &MigrationMessage::AgentGraphBinding(expected),
    )
    .await
    .unwrap();
    let ack = recv_message(&mut client_socket).await.unwrap();
    assert!(matches!(
        ack,
        MigrationMessage::AgentGraphBindingAck {
            accepted: true,
            error_message: None
        }
    ));

    server_handle.await.unwrap();
}
