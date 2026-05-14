#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/functional.h>

#include "device.hpp"
#include "ata.hpp"
#include "nvme.hpp"
#include "wipe.hpp"
#include "entropy.hpp"
#include "timing.hpp"

namespace py = pybind11;
using namespace zerotrace;

PYBIND11_MODULE(zerotrace_core, m) {
    m.doc() = "ZeroTrace C++ Core Engine";

    // ─── Enums ───────────────────────────────────────────────
    py::enum_<DriveType>(m, "DriveType")
        .value("HDD",       DriveType::HDD)
        .value("SSD_SATA",  DriveType::SSD_SATA)
        .value("SSD_NVME",  DriveType::SSD_NVME)
        .value("USB_DRIVE", DriveType::USB_DRIVE)
        .value("UNKNOWN",   DriveType::UNKNOWN)
        .export_values();

    py::enum_<WipeMode>(m, "WipeMode")
        .value("CLEAR",              WipeMode::CLEAR)
        .value("PURGE",              WipeMode::PURGE)
        .value("FIRMWARE_DELETION",  WipeMode::FIRMWARE_DELETION)
        .export_values();

    py::enum_<HealthStatus>(m, "HealthStatus")
        .value("PASSED",  HealthStatus::PASSED)
        .value("WARNING", HealthStatus::WARNING)
        .value("FAILED",  HealthStatus::FAILED)
        .value("UNKNOWN", HealthStatus::UNKNOWN)
        .export_values();

    // ─── SmartData ──────────────────────────────────────────
    py::class_<SmartData>(m, "SmartData")
        .def_readwrite("reallocated_sector_count",    &SmartData::reallocated_sector_count)
        .def_readwrite("pending_sector_count",        &SmartData::pending_sector_count)
        .def_readwrite("uncorrectable_sector_count",  &SmartData::uncorrectable_sector_count)
        .def_readwrite("power_on_hours",              &SmartData::power_on_hours)
        .def_readwrite("temperature_celsius",         &SmartData::temperature_celsius)
        .def_readwrite("wear_leveling_count",         &SmartData::wear_leveling_count)
        .def_readwrite("total_lbas_written",          &SmartData::total_lbas_written)
        .def_readwrite("overall_health",              &SmartData::overall_health)
        .def_readwrite("smart_supported",             &SmartData::smart_supported)
        .def_readwrite("smart_enabled",               &SmartData::smart_enabled);

    // ─── HiddenAreaStatus ───────────────────────────────────
    py::class_<HiddenAreaStatus>(m, "HiddenAreaStatus")
        .def_readwrite("hpa_detected",              &HiddenAreaStatus::hpa_detected)
        .def_readwrite("hpa_hidden_lbas",           &HiddenAreaStatus::hpa_hidden_lbas)
        .def_readwrite("native_max_lba",            &HiddenAreaStatus::native_max_lba)
        .def_readwrite("reported_max_lba",          &HiddenAreaStatus::reported_max_lba)
        .def_readwrite("dco_detected",              &HiddenAreaStatus::dco_detected)
        .def_readwrite("dco_native_max_lba",        &HiddenAreaStatus::dco_native_max_lba)
        .def_readwrite("dco_modification_present",  &HiddenAreaStatus::dco_modification_present)
        .def_readwrite("security_frozen",           &HiddenAreaStatus::security_frozen);

    // ─── DeviceInfo ─────────────────────────────────────────
    py::class_<DeviceInfo>(m, "DeviceInfo")
        .def_readwrite("device_path",      &DeviceInfo::device_path)
        .def_readwrite("model",            &DeviceInfo::model)
        .def_readwrite("serial",           &DeviceInfo::serial)
        .def_readwrite("firmware_version", &DeviceInfo::firmware_version)
        .def_readwrite("type",             &DeviceInfo::type)
        .def_readwrite("total_lbas",       &DeviceInfo::total_lbas)
        .def_readwrite("sector_size",      &DeviceInfo::sector_size)
        .def_readwrite("size_gb",          &DeviceInfo::size_gb)
        .def_readwrite("size_bytes",       &DeviceInfo::size_bytes)
        .def_readwrite("smart",            &DeviceInfo::smart)
        .def_readwrite("hidden",           &DeviceInfo::hidden)
        .def_readwrite("is_ssd",           &DeviceInfo::is_ssd)
        .def_readwrite("supports_ata_secure_erase",          &DeviceInfo::supports_ata_secure_erase)
        .def_readwrite("supports_ata_secure_erase_enhanced", &DeviceInfo::supports_ata_secure_erase_enhanced)
        .def_readwrite("supports_nvme_sanitize",             &DeviceInfo::supports_nvme_sanitize)
        .def_readwrite("supports_nvme_format",               &DeviceInfo::supports_nvme_format)
        .def_readwrite("supports_dco",                       &DeviceInfo::supports_dco)
        .def_readwrite("supports_hpa",                       &DeviceInfo::supports_hpa);

    // ─── WipeResult ─────────────────────────────────────────
    py::class_<WipeResult>(m, "WipeResult")
        .def_readwrite("success",                  &WipeResult::success)
        .def_readwrite("mode_used",                &WipeResult::mode_used)
        .def_readwrite("error_message",            &WipeResult::error_message)
        .def_readwrite("duration_seconds",         &WipeResult::duration_seconds)
        .def_readwrite("hpa_removed",              &WipeResult::hpa_removed)
        .def_readwrite("dco_restored",             &WipeResult::dco_restored)
        .def_readwrite("hidden_areas_covered",     &WipeResult::hidden_areas_covered)
        .def_readwrite("firmware_command_used",    &WipeResult::firmware_command_used)
        .def_readwrite("firmware_command_name",    &WipeResult::firmware_command_name)
        .def_readwrite("sha256_pre_wipe",          &WipeResult::sha256_pre_wipe)
        .def_readwrite("sha256_post_wipe",         &WipeResult::sha256_post_wipe)
        .def_readwrite("start_epoch",              &WipeResult::start_epoch)
        .def_readwrite("end_epoch",                &WipeResult::end_epoch);

    // ─── EntropyResult ──────────────────────────────────────
    py::class_<EntropyResult>(m, "EntropyResult")
        .def_readwrite("entropy_bits",        &EntropyResult::entropy_bits)
        .def_readwrite("state",               &EntropyResult::state)
        .def_readwrite("wipe_verified",       &EntropyResult::wipe_verified)
        .def_readwrite("blocks_sampled",      &EntropyResult::blocks_sampled)
        .def_readwrite("total_blocks",        &EntropyResult::total_blocks)
        .def_readwrite("sample_coverage_pct", &EntropyResult::sample_coverage_pct);

    // ─── Telemetry Engine ───────────────────────────────────
    py::class_<timing::TelemetryProfile>(m, "TelemetryProfile")
        .def_readwrite("mean_latency_cycles",     &timing::TelemetryProfile::mean_latency_cycles)
        .def_readwrite("median_latency_cycles",   &timing::TelemetryProfile::median_latency_cycles)
        .def_readwrite("std_deviation",           &timing::TelemetryProfile::std_deviation)
        .def_readwrite("raw_latencies",           &timing::TelemetryProfile::raw_latencies)
        .def_readwrite("statistically_anomalous", &timing::TelemetryProfile::statistically_anomalous)
        .def_readwrite("anomaly_p_value",         &timing::TelemetryProfile::anomaly_p_value);

    py::class_<timing::TelemetryEngine>(m, "TelemetryEngine")
        .def(py::init<const std::string &>(), py::arg("device_path"))
        .def("profile_entropy_high_state", &timing::TelemetryEngine::profile_entropy_high_state)
        .def("profile_entropy_low_state",  &timing::TelemetryEngine::profile_entropy_low_state)
        .def("execute_telemetry_scan",     &timing::TelemetryEngine::execute_telemetry_scan,
             py::arg("start_lba"), py::arg("sample_count"));

    // ─── Device Detection ───────────────────────────────────
    m.def("enumerate_block_devices", &enumerate_block_devices,
          "List all non-removable block devices on the system");

    m.def("scan_ata_device", &ata::scan_device,
          "Scan an ATA/SATA device and return full DeviceInfo",
          py::arg("device_path"));

    m.def("scan_nvme_device", &nvme::scan_nvme_device,
          "Scan an NVMe device and return full DeviceInfo",
          py::arg("nvme_ns_path"));

    // ─── Wipe Operations ────────────────────────────────────
    m.def("wipe_clear", &wipe_clear,
          "Zero-fill a device (NIST Clear)",
          py::arg("device"), py::arg("progress_cb"));

    m.def("wipe_purge", &wipe_purge,
          "Cryptographic purge (NIST Purge)",
          py::arg("device"), py::arg("progress_cb"));

    m.def("wipe_firmware", &wipe_firmware,
          "Firmware erase (ATA Secure Erase / NVMe Sanitize)",
          py::arg("device"), py::arg("progress_cb"));

    // ─── Entropy Analysis ───────────────────────────────────
    m.def("analyze_entropy", &analyze_entropy,
          "Run Shannon entropy analysis on device post-wipe",
          py::arg("device_path"), py::arg("mode_used"));

    // ─── Utilities ──────────────────────────────────────────
    m.def("hash_first_mb", &hash_first_mb,
          "Compute SHA-256 of first 1MB of a device",
          py::arg("device_path"));
}
