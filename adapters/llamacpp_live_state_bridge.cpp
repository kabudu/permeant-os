// Minimal PermeantOS llama.cpp live state bridge.
//
// This helper binds against the installed libllama C API. It exports a
// llama.cpp runtime state after prompt prefill, imports that state into a fresh
// target context, and proves the imported state produces the same greedy
// continuation as the source context.

#include <llama.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

struct Args {
    std::string mode = "roundtrip";
    std::string model;
    std::string prompt;
    std::string state_out;
    std::string state_in;
    int n_predict = 8;
    int n_ctx = 256;
    int threads = 4;
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
                std::snprintf(buf, sizeof(buf), "\\u%04x", ch);
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

uint64_t file_size(const std::string & path) {
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    if (!file) {
        return 0;
    }
    return static_cast<uint64_t>(file.tellg());
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
        if (key == "--mode") {
            args.mode = next();
        } else if (key == "--model") {
            args.model = next();
        } else if (key == "--prompt") {
            args.prompt = next();
        } else if (key == "--state-out") {
            args.state_out = next();
        } else if (key == "--state-in") {
            args.state_in = next();
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
    if (args.model.empty()) {
        throw std::runtime_error("--model is required");
    }
    if (args.n_predict < 0 || args.n_ctx <= 0 || args.threads <= 0) {
        throw std::runtime_error("invalid numeric argument");
    }
    return args;
}

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

std::vector<llama_token> tokenize(const Runtime & runtime, const std::string & text) {
    int32_t count = llama_tokenize(
        runtime.vocab,
        text.c_str(),
        static_cast<int32_t>(text.size()),
        nullptr,
        0,
        true,
        true);
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

std::vector<llama_token> load_state(Runtime & runtime, const std::string & state_path, int n_ctx) {
    std::vector<llama_token> tokens(static_cast<size_t>(n_ctx));
    size_t token_count = 0;
    bool ok = llama_state_load_file(
        runtime.ctx,
        state_path.c_str(),
        tokens.data(),
        tokens.size(),
        &token_count);
    if (!ok) {
        throw std::runtime_error("failed to load llama.cpp state file");
    }
    tokens.resize(token_count);
    return tokens;
}

void rehydrate_logits_from_loaded_state(Runtime & runtime, const std::vector<llama_token> & tokens) {
    if (tokens.empty()) {
        throw std::runtime_error("loaded state contained no tokens");
    }

    llama_memory_t memory = llama_get_memory(runtime.ctx);
    const llama_pos last_pos = static_cast<llama_pos>(tokens.size() - 1);
    if (!llama_memory_seq_rm(memory, 0, last_pos, last_pos + 1)) {
        throw std::runtime_error("failed to remove final imported token for logits rehydration");
    }
    decode_tokens(runtime, std::vector<llama_token>{tokens.back()}, last_pos);
}

void save_state(Runtime & runtime, const std::string & state_path, const std::vector<llama_token> & tokens) {
    bool ok = llama_state_save_file(
        runtime.ctx,
        state_path.c_str(),
        tokens.data(),
        tokens.size());
    if (!ok) {
        throw std::runtime_error("failed to save llama.cpp state file");
    }
}

void emit_roundtrip(const Args & args) {
    Runtime source(args.model, args.n_ctx, args.threads);
    std::vector<llama_token> prompt_tokens = tokenize(source, args.prompt);
    decode_tokens(source, prompt_tokens, 0);
    save_state(source, args.state_out, prompt_tokens);
    std::vector<llama_token> source_continuation =
        generate_greedy(source, static_cast<int32_t>(prompt_tokens.size()), args.n_predict);

    Runtime target(args.model, args.n_ctx, args.threads);
    std::vector<llama_token> loaded_tokens = load_state(target, args.state_out, args.n_ctx);
    rehydrate_logits_from_loaded_state(target, loaded_tokens);
    std::vector<llama_token> target_continuation =
        generate_greedy(target, static_cast<int32_t>(loaded_tokens.size()), args.n_predict);

    bool exact = source_continuation == target_continuation;
    std::cout
        << "{"
        << "\"success\":" << (exact ? "true" : "false") << ","
        << "\"mode\":\"roundtrip\","
        << "\"runtime\":\"llama.cpp\","
        << "\"used_migrated_kv\":true,"
        << "\"prompt_tokens\":" << json_tokens(prompt_tokens) << ","
        << "\"loaded_tokens\":" << json_tokens(loaded_tokens) << ","
        << "\"source_token_ids\":" << json_tokens(source_continuation) << ","
        << "\"target_token_ids\":" << json_tokens(target_continuation) << ","
        << "\"continuation_exact\":" << (exact ? "true" : "false") << ","
        << "\"kv_token_count\":" << loaded_tokens.size() << ","
        << "\"state_file\":\"" << json_escape(args.state_out) << "\","
        << "\"state_bytes\":" << file_size(args.state_out)
        << "}\n";
    if (!exact) {
        std::exit(2);
    }
}

void emit_continue_state(const Args & args) {
    Runtime target(args.model, args.n_ctx, args.threads);
    std::vector<llama_token> loaded_tokens = load_state(target, args.state_in, args.n_ctx);
    rehydrate_logits_from_loaded_state(target, loaded_tokens);
    std::vector<llama_token> continuation =
        generate_greedy(target, static_cast<int32_t>(loaded_tokens.size()), args.n_predict);
    std::cout
        << "{"
        << "\"success\":true,"
        << "\"mode\":\"continue-state\","
        << "\"runtime\":\"llama.cpp\","
        << "\"used_migrated_kv\":true,"
        << "\"loaded_tokens\":" << json_tokens(loaded_tokens) << ","
        << "\"target_token_ids\":" << json_tokens(continuation) << ","
        << "\"kv_token_count\":" << loaded_tokens.size() << ","
        << "\"state_file\":\"" << json_escape(args.state_in) << "\","
        << "\"state_bytes\":" << file_size(args.state_in)
        << "}\n";
}

} // namespace

int main(int argc, char ** argv) {
    try {
        Args args = parse_args(argc, argv);
        ggml_backend_load_all();
        llama_backend_init();
        if (args.mode == "roundtrip") {
            if (args.prompt.empty() || args.state_out.empty()) {
                throw std::runtime_error("roundtrip requires --prompt and --state-out");
            }
            emit_roundtrip(args);
        } else if (args.mode == "continue-state") {
            if (args.state_in.empty()) {
                throw std::runtime_error("continue-state requires --state-in");
            }
            emit_continue_state(args);
        } else {
            throw std::runtime_error("unsupported mode: " + args.mode);
        }
        llama_backend_free();
    } catch (const std::exception & exc) {
        fail(exc.what());
    }
}
