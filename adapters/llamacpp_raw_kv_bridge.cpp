// PermeantOS llama.cpp raw KV tensor proof bridge.
//
// This helper intentionally binds against llama.cpp private headers from a
// matching source checkout. It exports canonical f32 K/V rows from one live
// context and writes those values directly into another context's internal
// cache_k_l*/cache_v_l* ggml backend tensors. The proof corrupts target KV
// first, verifies decode changes, restores from canonical f32 tensors, and
// verifies decode returns to the clean/source continuation.

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include <llama.h>

// Pull private KV cache fields into this proof helper. This file must be
// compiled with -I pointing at the matching llama.cpp src/ directory.
#define private public
#include "llama-kv-cache.h"
#undef private

namespace {

struct Args {
    std::string model;
    std::string prompt;
    int n_predict = 8;
    int n_ctx = 256;
    int threads = 4;
};

struct CanonicalLayer {
    uint32_t il = 0;
    int64_t seq_len = 0;
    int64_t k_width = 0;
    int64_t v_width = 0;
    std::vector<float> key;
    std::vector<float> value;
};

struct Runtime {
    llama_model * model = nullptr;
    llama_context * ctx = nullptr;
    const llama_vocab * vocab = nullptr;

    Runtime(const std::string & model_path, int n_ctx, int threads) {
        llama_model_params model_params = llama_model_default_params();
        model = llama_model_load_from_file(model_path.c_str(), model_params);
        if (!model) {
            throw std::runtime_error("failed to load llama.cpp model");
        }

        llama_context_params ctx_params = llama_context_default_params();
        ctx_params.n_ctx = static_cast<uint32_t>(n_ctx);
        ctx_params.n_batch = static_cast<uint32_t>(n_ctx);
        ctx_params.n_ubatch = static_cast<uint32_t>(n_ctx);
        ctx_params.n_seq_max = 1;
        ctx = llama_init_from_model(model, ctx_params);
        if (!ctx) {
            throw std::runtime_error("failed to create llama.cpp context");
        }
        llama_set_n_threads(ctx, threads, threads);
        vocab = llama_model_get_vocab(model);
    }

    ~Runtime() {
        if (ctx) {
            llama_free(ctx);
        }
        if (model) {
            llama_model_free(model);
        }
    }
};

[[noreturn]] void fail(const std::string & message) {
    std::cout << "{\"success\":false,\"error\":\"" << message << "\"}\n";
    std::exit(1);
}

std::string json_escape(const std::string & value) {
    std::ostringstream out;
    for (char ch : value) {
        switch (ch) {
        case '\\': out << "\\\\"; break;
        case '"': out << "\\\""; break;
        case '\n': out << "\\n"; break;
        case '\r': out << "\\r"; break;
        case '\t': out << "\\t"; break;
        default:
            if (static_cast<unsigned char>(ch) < 0x20) {
                char buf[7];
                std::snprintf(buf, sizeof(buf), "\\u%04x", static_cast<unsigned char>(ch));
                out << buf;
            } else {
                out << ch;
            }
        }
    }
    return out.str();
}

std::string json_tokens(const std::vector<llama_token> & tokens) {
    std::ostringstream out;
    out << "[";
    for (size_t i = 0; i < tokens.size(); ++i) {
        if (i) {
            out << ",";
        }
        out << tokens[i];
    }
    out << "]";
    return out.str();
}

uint64_t fnv1a_bytes(const void * data, size_t size, uint64_t seed = 1469598103934665603ull) {
    const auto * ptr = static_cast<const uint8_t *>(data);
    uint64_t hash = seed;
    for (size_t i = 0; i < size; ++i) {
        hash ^= ptr[i];
        hash *= 1099511628211ull;
    }
    return hash;
}

uint64_t hash_f32(const std::vector<float> & values, uint64_t seed = 1469598103934665603ull) {
    return fnv1a_bytes(values.data(), values.size() * sizeof(float), seed);
}

std::string hex64(uint64_t value) {
    std::ostringstream out;
    out << "fnv1a64:" << std::hex << std::setfill('0') << std::setw(16) << value;
    return out.str();
}

Args parse_args(int argc, char ** argv) {
    Args args;
    for (int i = 1; i < argc; ++i) {
        std::string key = argv[i];
        auto next = [&]() -> std::string {
            if (i + 1 >= argc) {
                throw std::runtime_error("missing value for " + key);
            }
            return argv[++i];
        };
        if (key == "--model") {
            args.model = next();
        } else if (key == "--prompt") {
            args.prompt = next();
        } else if (key == "--n-predict") {
            args.n_predict = std::stoi(next());
        } else if (key == "--ctx-size") {
            args.n_ctx = std::stoi(next());
        } else if (key == "--threads") {
            args.threads = std::stoi(next());
        } else {
            throw std::runtime_error("unknown argument: " + key);
        }
    }
    if (args.model.empty() || args.prompt.empty()) {
        throw std::runtime_error("--model and --prompt are required");
    }
    if (args.n_predict <= 0 || args.n_ctx <= 0 || args.threads <= 0) {
        throw std::runtime_error("invalid numeric argument");
    }
    return args;
}

std::vector<llama_token> tokenize(const Runtime & runtime, const std::string & text) {
    int32_t count = llama_tokenize(runtime.vocab, text.c_str(), static_cast<int32_t>(text.size()), nullptr, 0, true, true);
    if (count == INT32_MIN) {
        throw std::runtime_error("tokenization overflow");
    }
    if (count < 0) {
        count = -count;
    }
    std::vector<llama_token> tokens(count);
    int32_t written = llama_tokenize(
        runtime.vocab,
        text.c_str(),
        static_cast<int32_t>(text.size()),
        tokens.data(),
        static_cast<int32_t>(tokens.size()),
        true,
        true);
    if (written < 0 || written > static_cast<int32_t>(tokens.size())) {
        throw std::runtime_error("failed to tokenize prompt");
    }
    tokens.resize(written);
    if (tokens.empty()) {
        throw std::runtime_error("prompt produced no tokens");
    }
    return tokens;
}

void decode_tokens(Runtime & runtime, const std::vector<llama_token> & tokens, int32_t pos_start) {
    llama_batch batch = llama_batch_init(static_cast<int32_t>(tokens.size()), 0, 1);
    llama_seq_id seq_id = 0;
    for (int32_t i = 0; i < static_cast<int32_t>(tokens.size()); ++i) {
        batch.token[i] = tokens[i];
        batch.pos[i] = pos_start + i;
        batch.n_seq_id[i] = 1;
        batch.seq_id[i][0] = seq_id;
        batch.logits[i] = i == static_cast<int32_t>(tokens.size()) - 1 ? 1 : 0;
    }
    batch.n_tokens = static_cast<int32_t>(tokens.size());
    int32_t rc = llama_decode(runtime.ctx, batch);
    llama_batch_free(batch);
    if (rc != 0) {
        throw std::runtime_error("llama_decode failed with code " + std::to_string(rc));
    }
    llama_synchronize(runtime.ctx);
}

std::vector<llama_token> generate_greedy(Runtime & runtime, int32_t start_pos, int n_predict) {
    std::vector<llama_token> generated;
    llama_sampler * sampler = llama_sampler_init_greedy();
    if (!sampler) {
        throw std::runtime_error("failed to initialize greedy sampler");
    }
    for (int i = 0; i < n_predict; ++i) {
        llama_token token = llama_sampler_sample(sampler, runtime.ctx, -1);
        llama_sampler_accept(sampler, token);
        generated.push_back(token);
        if (llama_vocab_is_eog(runtime.vocab, token)) {
            break;
        }
        decode_tokens(runtime, std::vector<llama_token>{token}, start_pos + i);
    }
    llama_sampler_free(sampler);
    return generated;
}

llama_kv_cache * kv_cache(Runtime & runtime) {
    llama_memory_t memory = llama_get_memory(runtime.ctx);
    auto * kv = dynamic_cast<llama_kv_cache *>(memory);
    if (!kv) {
        throw std::runtime_error("context memory is not a llama_kv_cache");
    }
    return kv;
}

std::vector<uint8_t> tensor_bytes(ggml_tensor * tensor, size_t offset, size_t size) {
    std::vector<uint8_t> bytes(size);
    ggml_backend_tensor_get(tensor, bytes.data(), offset, size);
    return bytes;
}

std::vector<float> read_rows_as_f32(ggml_tensor * tensor, int64_t width, int64_t row_count) {
    if (tensor->type != GGML_TYPE_F16 && tensor->type != GGML_TYPE_F32) {
        throw std::runtime_error("raw KV proof supports only f16/f32 KV cache tensors");
    }
    const size_t el_size = ggml_type_size(tensor->type);
    const size_t row_bytes = static_cast<size_t>(width) * el_size;
    std::vector<float> values(static_cast<size_t>(width * row_count));
    std::vector<uint8_t> row(row_bytes);
    for (int64_t row_index = 0; row_index < row_count; ++row_index) {
        const size_t offset = static_cast<size_t>(row_index) * tensor->nb[1];
        ggml_backend_tensor_get(tensor, row.data(), offset, row_bytes);
        if (tensor->type == GGML_TYPE_F32) {
            std::memcpy(values.data() + row_index * width, row.data(), row_bytes);
        } else {
            ggml_fp16_to_fp32_row(reinterpret_cast<const ggml_fp16_t *>(row.data()), values.data() + row_index * width, width);
        }
    }
    return values;
}

std::vector<float> read_transposed_v_as_f32(ggml_tensor * tensor, int64_t width, int64_t row_count, int64_t kv_size) {
    if (tensor->type != GGML_TYPE_F16 && tensor->type != GGML_TYPE_F32) {
        throw std::runtime_error("raw KV proof supports only f16/f32 KV cache tensors");
    }
    const size_t el_size = ggml_type_size(tensor->type);
    std::vector<float> values(static_cast<size_t>(width * row_count));
    std::vector<uint8_t> encoded(static_cast<size_t>(row_count) * el_size);
    for (int64_t dim = 0; dim < width; ++dim) {
        const size_t src_offset = static_cast<size_t>(dim * kv_size) * el_size;
        ggml_backend_tensor_get(tensor, encoded.data(), src_offset, encoded.size());
        if (tensor->type == GGML_TYPE_F32) {
            const auto * src = reinterpret_cast<const float *>(encoded.data());
            for (int64_t row = 0; row < row_count; ++row) {
                values[static_cast<size_t>(row * width + dim)] = src[row];
            }
        } else {
            std::vector<float> tmp(static_cast<size_t>(row_count));
            ggml_fp16_to_fp32_row(reinterpret_cast<const ggml_fp16_t *>(encoded.data()), tmp.data(), row_count);
            for (int64_t row = 0; row < row_count; ++row) {
                values[static_cast<size_t>(row * width + dim)] = tmp[static_cast<size_t>(row)];
            }
        }
    }
    return values;
}

std::vector<uint8_t> encode_rows_from_f32(ggml_type type, const std::vector<float> & values) {
    if (type != GGML_TYPE_F16 && type != GGML_TYPE_F32) {
        throw std::runtime_error("raw KV proof supports only f16/f32 KV cache tensors");
    }
    if (type == GGML_TYPE_F32) {
        std::vector<uint8_t> bytes(values.size() * sizeof(float));
        std::memcpy(bytes.data(), values.data(), bytes.size());
        return bytes;
    }
    std::vector<ggml_fp16_t> halves(values.size());
    ggml_fp32_to_fp16_row(values.data(), halves.data(), values.size());
    std::vector<uint8_t> bytes(halves.size() * sizeof(ggml_fp16_t));
    std::memcpy(bytes.data(), halves.data(), bytes.size());
    return bytes;
}

std::vector<CanonicalLayer> export_canonical(Runtime & runtime, int64_t seq_len) {
    llama_kv_cache * kv = kv_cache(runtime);
    if (kv->get_n_stream() != 1 || kv->v_cells.empty()) {
        throw std::runtime_error("raw KV proof currently requires a single-stream llama.cpp KV cache");
    }
    const int64_t kv_size = kv->v_cells[0].size();
    std::vector<CanonicalLayer> layers;
    for (const auto & layer : kv->layers) {
        if (!layer.k || !layer.v) {
            continue;
        }
        CanonicalLayer out;
        out.il = layer.il;
        out.seq_len = seq_len;
        out.k_width = layer.k->ne[0];
        out.v_width = kv->v_trans ? kv->hparams.n_embd_v_gqa(layer.il) : layer.v->ne[0];
        out.key = read_rows_as_f32(layer.k, out.k_width, seq_len);
        out.value = kv->v_trans
            ? read_transposed_v_as_f32(layer.v, out.v_width, seq_len, kv_size)
            : read_rows_as_f32(layer.v, out.v_width, seq_len);
        layers.push_back(std::move(out));
    }
    return layers;
}

uint64_t canonical_hash(const std::vector<CanonicalLayer> & layers) {
    uint64_t hash = 1469598103934665603ull;
    for (const auto & layer : layers) {
        hash = fnv1a_bytes(&layer.il, sizeof(layer.il), hash);
        hash = fnv1a_bytes(&layer.seq_len, sizeof(layer.seq_len), hash);
        hash = fnv1a_bytes(&layer.k_width, sizeof(layer.k_width), hash);
        hash = fnv1a_bytes(&layer.v_width, sizeof(layer.v_width), hash);
        hash = hash_f32(layer.key, hash);
        hash = hash_f32(layer.value, hash);
    }
    return hash;
}

void write_layer_rows(ggml_tensor * tensor, int64_t width, int64_t row_count, const std::vector<float> & values) {
    const size_t el_size = ggml_type_size(tensor->type);
    const size_t row_bytes = static_cast<size_t>(width) * el_size;
    std::vector<uint8_t> encoded = encode_rows_from_f32(tensor->type, values);
    if (encoded.size() != row_bytes * static_cast<size_t>(row_count)) {
        throw std::runtime_error("encoded KV tensor size mismatch");
    }
    for (int64_t row_index = 0; row_index < row_count; ++row_index) {
        const size_t src_offset = static_cast<size_t>(row_index) * row_bytes;
        const size_t dst_offset = static_cast<size_t>(row_index) * tensor->nb[1];
        ggml_backend_tensor_set(tensor, encoded.data() + src_offset, dst_offset, row_bytes);
    }
}

void write_transposed_v_rows(
    ggml_tensor * tensor,
    int64_t width,
    int64_t row_count,
    int64_t kv_size,
    const std::vector<float> & values) {
    if (tensor->type != GGML_TYPE_F16 && tensor->type != GGML_TYPE_F32) {
        throw std::runtime_error("raw KV proof supports only f16/f32 KV cache tensors");
    }
    const size_t el_size = ggml_type_size(tensor->type);
    std::vector<float> column(static_cast<size_t>(row_count));
    for (int64_t dim = 0; dim < width; ++dim) {
        for (int64_t row = 0; row < row_count; ++row) {
            column[static_cast<size_t>(row)] = values[static_cast<size_t>(row * width + dim)];
        }
        std::vector<uint8_t> encoded = encode_rows_from_f32(tensor->type, column);
        const size_t dst_offset = static_cast<size_t>(dim * kv_size) * el_size;
        ggml_backend_tensor_set(tensor, encoded.data(), dst_offset, encoded.size());
    }
}

void import_canonical(Runtime & runtime, const std::vector<CanonicalLayer> & layers) {
    llama_kv_cache * kv = kv_cache(runtime);
    if (kv->get_n_stream() != 1 || kv->v_cells.empty()) {
        throw std::runtime_error("raw KV proof currently requires a single-stream llama.cpp KV cache");
    }
    const int64_t kv_size = kv->v_cells[0].size();
    if (layers.size() > kv->layers.size()) {
        throw std::runtime_error("canonical layer count exceeds target KV layer count");
    }
    for (size_t i = 0; i < layers.size(); ++i) {
        const auto & src = layers[i];
        const auto & dst = kv->layers[i];
        const int64_t dst_v_width = kv->v_trans ? kv->hparams.n_embd_v_gqa(dst.il) : dst.v->ne[0];
        if (!dst.k || !dst.v || dst.il != src.il || dst.k->ne[0] != src.k_width || dst_v_width != src.v_width) {
            throw std::runtime_error("canonical KV layer geometry does not match llama.cpp target");
        }
        write_layer_rows(dst.k, src.k_width, src.seq_len, src.key);
        if (kv->v_trans) {
            write_transposed_v_rows(dst.v, src.v_width, src.seq_len, kv_size, src.value);
        } else {
            write_layer_rows(dst.v, src.v_width, src.seq_len, src.value);
        }
    }
    llama_synchronize(runtime.ctx);
}

void fill_kv(Runtime & runtime, int64_t seq_len, float value) {
    llama_kv_cache * kv = kv_cache(runtime);
    if (kv->get_n_stream() != 1 || kv->v_cells.empty()) {
        throw std::runtime_error("raw KV proof currently requires a single-stream llama.cpp KV cache");
    }
    const int64_t kv_size = kv->v_cells[0].size();
    for (const auto & layer : kv->layers) {
        if (!layer.k || !layer.v) {
            continue;
        }
        const int64_t v_width = kv->v_trans ? kv->hparams.n_embd_v_gqa(layer.il) : layer.v->ne[0];
        std::vector<float> key(static_cast<size_t>(seq_len * layer.k->ne[0]), value);
        std::vector<float> val(static_cast<size_t>(seq_len * v_width), value);
        write_layer_rows(layer.k, layer.k->ne[0], seq_len, key);
        if (kv->v_trans) {
            write_transposed_v_rows(layer.v, v_width, seq_len, kv_size, val);
        } else {
            write_layer_rows(layer.v, v_width, seq_len, val);
        }
    }
    llama_synchronize(runtime.ctx);
}

void rehydrate_logits(Runtime & runtime, const std::vector<llama_token> & prompt_tokens) {
    if (prompt_tokens.empty()) {
        throw std::runtime_error("cannot rehydrate logits for empty prompt");
    }
    llama_memory_t memory = llama_get_memory(runtime.ctx);
    const llama_pos last_pos = static_cast<llama_pos>(prompt_tokens.size() - 1);
    if (!llama_memory_seq_rm(memory, 0, last_pos, last_pos + 1)) {
        throw std::runtime_error("failed to remove final token for logits rehydration");
    }
    decode_tokens(runtime, std::vector<llama_token>{prompt_tokens.back()}, last_pos);
}

void emit_proof(const Args & args) {
    Runtime source(args.model, args.n_ctx, args.threads);
    std::vector<llama_token> prompt_tokens = tokenize(source, args.prompt);
    decode_tokens(source, prompt_tokens, 0);
    std::vector<CanonicalLayer> canonical = export_canonical(source, prompt_tokens.size());
    const uint64_t exported_hash = canonical_hash(canonical);
    std::vector<llama_token> source_continuation =
        generate_greedy(source, static_cast<int32_t>(prompt_tokens.size()), args.n_predict);

    Runtime target_corrupt(args.model, args.n_ctx, args.threads);
    decode_tokens(target_corrupt, prompt_tokens, 0);
    fill_kv(target_corrupt, static_cast<int64_t>(prompt_tokens.size()), 7.0f);
    rehydrate_logits(target_corrupt, prompt_tokens);
    std::vector<llama_token> corrupt_continuation =
        generate_greedy(target_corrupt, static_cast<int32_t>(prompt_tokens.size()), args.n_predict);

    Runtime target_restore(args.model, args.n_ctx, args.threads);
    decode_tokens(target_restore, prompt_tokens, 0);
    fill_kv(target_restore, static_cast<int64_t>(prompt_tokens.size()), 7.0f);
    import_canonical(target_restore, canonical);
    std::vector<CanonicalLayer> restored = export_canonical(target_restore, prompt_tokens.size());
    const uint64_t restored_hash = canonical_hash(restored);
    rehydrate_logits(target_restore, prompt_tokens);
    std::vector<llama_token> restored_continuation =
        generate_greedy(target_restore, static_cast<int32_t>(prompt_tokens.size()), args.n_predict);

    const bool corrupt_changed = corrupt_continuation != source_continuation;
    const bool restored_exact = restored_continuation == source_continuation;
    const bool hashes_exact = exported_hash == restored_hash;
    const bool success = corrupt_changed && restored_exact && hashes_exact;

    std::cout
        << "{"
        << "\"success\":" << (success ? "true" : "false") << ","
        << "\"mode\":\"raw-internal-kv\","
        << "\"runtime\":\"llama.cpp\","
        << "\"used_state_file\":false,"
        << "\"used_internal_kv_tensor_write\":true,"
        << "\"prompt_tokens\":" << json_tokens(prompt_tokens) << ","
        << "\"source_token_ids\":" << json_tokens(source_continuation) << ","
        << "\"corrupt_token_ids\":" << json_tokens(corrupt_continuation) << ","
        << "\"restored_token_ids\":" << json_tokens(restored_continuation) << ","
        << "\"corrupt_changed_continuation\":" << (corrupt_changed ? "true" : "false") << ","
        << "\"restored_exact\":" << (restored_exact ? "true" : "false") << ","
        << "\"canonical_hash_exact\":" << (hashes_exact ? "true" : "false") << ","
        << "\"canonical_hash\":\"" << hex64(exported_hash) << "\","
        << "\"restored_hash\":\"" << hex64(restored_hash) << "\","
        << "\"layer_count\":" << canonical.size() << ","
        << "\"kv_token_count\":" << prompt_tokens.size();
    if (!canonical.empty()) {
        std::cout
            << ",\"first_layer\":{\"il\":" << canonical.front().il
            << ",\"seq_len\":" << canonical.front().seq_len
            << ",\"k_width\":" << canonical.front().k_width
            << ",\"v_width\":" << canonical.front().v_width
            << "}";
    }
    std::cout << "}\n";
    if (!success) {
        std::exit(2);
    }
}

} // namespace

int main(int argc, char ** argv) {
    try {
        Args args = parse_args(argc, argv);
        ggml_backend_load_all();
        llama_backend_init();
        emit_proof(args);
        llama_backend_free();
    } catch (const std::exception & exc) {
        fail(exc.what());
    }
}
