use tokio::net::{TcpListener, TcpStream};
use permeant_transport::{AgentGraphBinding, AgentGraphBindingKvSpan, send_message, recv_message, MigrationMessage, compute_crc32, verify_chunk_crc32};
use usxf_core::crypto::{seal_packet, open_packet, SigningKey};
use usxf_core::{UsxfHeader, AttentionType, ModelIdentity, ModelCacheSpec, ExchangeDtype};
use std::collections::HashMap;
use chrono::Utc;

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
        if let MigrationMessage::CapabilityRequest { model_architecture, .. } = cap_req {
            assert_eq!(model_architecture, "Llama-3.1-8B-Mock");
            
            // Accept it
            send_message(&mut socket, &MigrationMessage::CapabilityResponse {
                accepted: true,
                error_message: None,
                target_device: "Metal/Mock".to_string(),
            }).await.unwrap();
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
            
            send_message(&mut socket, &MigrationMessage::HeaderAck { accepted: true }).await.unwrap();
        } else {
            panic!("Expected HeaderEnvelope");
        }
    });
    
    // 2. Client connection
    let mut client_socket = TcpStream::connect(local_addr).await.unwrap();
    
    // Send CapabilityRequest
    send_message(&mut client_socket, &MigrationMessage::CapabilityRequest {
        model_architecture: "Llama-3.1-8B-Mock".to_string(),
        attention_type: "gqa".to_string(),
        seq_len: 123,
    }).await.unwrap();
    
    // Recv CapabilityResponse
    let resp = recv_message(&mut client_socket).await.unwrap();
    if let MigrationMessage::CapabilityResponse { accepted, target_device, .. } = resp {
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
            config_hash: "sha256:7f8e9a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f".to_string(),
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
        checksum: "sha256:0000000000000000000000000000000000000000000000000000000000000000".to_string(),
        signature: "".to_string(),
    };
    
    let aes_key = [5u8; 32];
    let mut csprng = rand::rngs::OsRng;
    let signing_key = SigningKey::generate(&mut csprng);
    let serialized_header = serde_json::to_vec(&header).unwrap();
    let envelope = seal_packet(&serialized_header, &aes_key, &signing_key).unwrap();
    
    send_message(&mut client_socket, &MigrationMessage::HeaderEnvelope(envelope)).await.unwrap();
    
    let ack = recv_message(&mut client_socket).await.unwrap();
    if let MigrationMessage::HeaderAck { accepted } = ack {
        assert!(accepted);
    } else {
        panic!("Expected HeaderAck");
    }
    
    server_handle.await.unwrap();
}

#[tokio::test]
async fn test_crc32_corruption_handling() {
    let raw_payload = vec![1u8, 2, 3, 4, 5];
    let correct_crc = compute_crc32(&raw_payload);
    
    let valid_chunk = MigrationMessage::PayloadChunk {
        chunk_index: 0,
        layer_index: 0,
        tensor_name: "layer.0.key".to_string(),
        data: raw_payload.clone(),
        crc32: correct_crc,
    };
    
    // Verify valid chunk passes
    assert!(verify_chunk_crc32(&valid_chunk).unwrap());
    
    let corrupted_chunk = MigrationMessage::PayloadChunk {
        chunk_index: 0,
        layer_index: 0,
        tensor_name: "layer.0.key".to_string(),
        data: raw_payload.clone(),
        crc32: correct_crc ^ 1234, // modify CRC32
    };
    
    // Verify corrupted chunk fails
    assert!(!verify_chunk_crc32(&corrupted_chunk).unwrap());
}

#[tokio::test]
async fn test_protocol_abort_mid_stream() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let local_addr = listener.local_addr().unwrap();
    
    // Spawn server that expects CapabilityRequest then closed socket
    let server_handle = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let cap_req = recv_message(&mut socket).await.unwrap();
        assert!(matches!(cap_req, MigrationMessage::CapabilityRequest { .. }));
        
        // Wait for next message which will fail because client abruptly disconnects
        let next_msg = recv_message(&mut socket).await;
        assert!(next_msg.is_err(), "Expected connection error on abrupt close");
    });
    
    let mut client_socket = TcpStream::connect(local_addr).await.unwrap();
    send_message(&mut client_socket, &MigrationMessage::CapabilityRequest {
        model_architecture: "Llama-3.1-8B-Mock".to_string(),
        attention_type: "gqa".to_string(),
        seq_len: 100,
    }).await.unwrap();
    
    // Drop socket to simulate abrupt crash / timeout
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
        graph_hash: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa".to_string(),
        prompt_byte_hash: Some("sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb".to_string()),
        prompt_token_hash: Some("sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc".to_string()),
        tokenizer_hash: Some("sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd".to_string()),
        kv_hash: Some("sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee".to_string()),
        kv_spans: vec![AgentGraphBindingKvSpan {
            node_id: "checkpoint:prompt".to_string(),
            token_start: 0,
            token_end: 8,
            cache_ref: "kv:prefix:0".to_string(),
            tokenizer_hash: Some("sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd".to_string()),
            block_hashes: vec!["sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff".to_string()],
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
        send_message(&mut socket, &MigrationMessage::AgentGraphBindingAck {
            accepted: true,
            error_message: None,
        }).await.unwrap();
    });

    let mut client_socket = TcpStream::connect(local_addr).await.unwrap();
    send_message(&mut client_socket, &MigrationMessage::AgentGraphBinding(expected)).await.unwrap();
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
