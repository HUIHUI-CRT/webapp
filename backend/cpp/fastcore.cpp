// fastcore.cpp —— 计算密集型任务的 C++ 实现，通过 pybind11 暴露给 Python。
//
// 暴露接口（与 backend/app/ext/fallback.py 保持一致）：
//     sha256_file(path) -> str          流式计算文件 SHA-256
//     merge_chunks(paths, output) -> int 按顺序合并分块文件，返回字节数
//     engine() -> str                   引擎标识，固定返回 "cpp"
//
// 依赖：pybind11 头文件 + C++17 编译器。构建方式见 backend/cpp/CMakeLists.txt
// 与 scripts/build_ext.ps1。

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <array>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace py = pybind11;

namespace {

// ------------------------------------------------------------ SHA-256 实现
// 自带实现，避免引入 OpenSSL 等第三方依赖，保证扩展可独立编译。
class Sha256 {
public:
    Sha256() { reset(); }

    void reset() {
        h_ = {0x6a09e667u, 0xbb67ae85u, 0x3c6ef372u, 0xa54ff53au,
              0x510e527fu, 0x9b05688cu, 0x1f83d9abu, 0x5be0cd19u};
        buffer_.fill(0);
        buffer_len_ = 0;
        total_len_ = 0;
    }

    void update(const uint8_t* data, size_t len) {
        total_len_ += len;
        while (len > 0) {
            const size_t take = (len < (64 - buffer_len_)) ? len : (64 - buffer_len_);
            for (size_t i = 0; i < take; ++i) buffer_[buffer_len_ + i] = data[i];
            buffer_len_ += take;
            data += take;
            len -= take;
            if (buffer_len_ == 64) {
                transform(buffer_.data());
                buffer_len_ = 0;
            }
        }
    }

    std::string hex() {
        const uint64_t bit_len = total_len_ * 8ull;
        const uint8_t pad = 0x80;
        update(&pad, 1);
        const uint8_t zero = 0x00;
        while (buffer_len_ != 56) update(&zero, 1);
        uint8_t len_be[8];
        for (int i = 0; i < 8; ++i) len_be[i] = static_cast<uint8_t>(bit_len >> (56 - 8 * i));
        update(len_be, 8);

        std::ostringstream oss;
        for (uint32_t word : h_)
            oss << std::hex << std::setw(8) << std::setfill('0') << word;
        return oss.str();
    }

private:
    static uint32_t rotr(uint32_t x, uint32_t n) { return (x >> n) | (x << (32 - n)); }

    void transform(const uint8_t* block) {
        static const uint32_t k[64] = {
            0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u, 0x3956c25bu, 0x59f111f1u,
            0x923f82a4u, 0xab1c5ed5u, 0xd807aa98u, 0x12835b01u, 0x243185beu, 0x550c7dc3u,
            0x72be5d74u, 0x80deb1feu, 0x9bdc06a7u, 0xc19bf174u, 0xe49b69c1u, 0xefbe4786u,
            0x0fc19dc6u, 0x240ca1ccu, 0x2de92c6fu, 0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau,
            0x983e5152u, 0xa831c66du, 0xb00327c8u, 0xbf597fc7u, 0xc6e00bf3u, 0xd5a79147u,
            0x06ca6351u, 0x14292967u, 0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu, 0x53380d13u,
            0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u, 0xa2bfe8a1u, 0xa81a664bu,
            0xc24b8b70u, 0xc76c51a3u, 0xd192e819u, 0xd6990624u, 0xf40e3585u, 0x106aa070u,
            0x19a4c116u, 0x1e376c08u, 0x2748774cu, 0x34b0bcb5u, 0x391c0cb3u, 0x4ed8aa4au,
            0x5b9cca4fu, 0x682e6ff3u, 0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u,
            0x90befffau, 0xa4506cebu, 0xbef9a3f7u, 0xc67178f2u};

        uint32_t w[64];
        for (int i = 0; i < 16; ++i) {
            w[i] = (static_cast<uint32_t>(block[i * 4]) << 24) |
                   (static_cast<uint32_t>(block[i * 4 + 1]) << 16) |
                   (static_cast<uint32_t>(block[i * 4 + 2]) << 8) |
                   (static_cast<uint32_t>(block[i * 4 + 3]));
        }
        for (int i = 16; i < 64; ++i) {
            const uint32_t s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
            const uint32_t s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16] + s0 + w[i - 7] + s1;
        }

        uint32_t a = h_[0], b = h_[1], c = h_[2], d = h_[3];
        uint32_t e = h_[4], f = h_[5], g = h_[6], hh = h_[7];
        for (int i = 0; i < 64; ++i) {
            const uint32_t s1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
            const uint32_t ch = (e & f) ^ ((~e) & g);
            const uint32_t t1 = hh + s1 + ch + k[i] + w[i];
            const uint32_t s0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
            const uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
            const uint32_t t2 = s0 + maj;
            hh = g; g = f; f = e; e = d + t1;
            d = c; c = b; b = a; a = t1 + t2;
        }
        h_[0] += a; h_[1] += b; h_[2] += c; h_[3] += d;
        h_[4] += e; h_[5] += f; h_[6] += g; h_[7] += hh;
    }

    std::array<uint32_t, 8> h_{};
    std::array<uint8_t, 64> buffer_{};
    size_t buffer_len_ = 0;
    uint64_t total_len_ = 0;
};

constexpr size_t kBufferSize = 1u << 20;  // 1 MiB

}  // namespace

std::string sha256_file(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("无法打开文件: " + path);

    Sha256 hasher;
    std::vector<char> buffer(kBufferSize);
    while (in) {
        in.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
        const std::streamsize got = in.gcount();
        if (got > 0) hasher.update(reinterpret_cast<const uint8_t*>(buffer.data()),
                                  static_cast<size_t>(got));
    }
    return hasher.hex();
}

uint64_t merge_chunks(const std::vector<std::string>& paths, const std::string& output) {
    std::ofstream out(output, std::ios::binary | std::ios::trunc);
    if (!out) throw std::runtime_error("无法写入文件: " + output);

    std::vector<char> buffer(kBufferSize);
    uint64_t total = 0;
    for (const std::string& item : paths) {
        std::ifstream in(item, std::ios::binary);
        if (!in) throw std::runtime_error("无法打开分块文件: " + item);
        while (in) {
            in.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
            const std::streamsize got = in.gcount();
            if (got > 0) {
                out.write(buffer.data(), got);
                total += static_cast<uint64_t>(got);
            }
        }
    }
    out.flush();
    return total;
}

std::string engine() { return "cpp"; }

PYBIND11_MODULE(fastcore, m) {
    m.doc() = "C++ 性能扩展：SHA-256 计算与分块文件合并";
    m.def("sha256_file", &sha256_file, py::arg("path"), "流式计算文件 SHA-256，返回十六进制字符串");
    m.def("merge_chunks", &merge_chunks, py::arg("paths"), py::arg("output"),
          "按顺序合并分块文件，返回写入字节数");
    m.def("engine", &engine, "返回引擎标识");
    m.attr("__version__") = "1.0.0";
}
