#pragma once

#include <string>
#include <cstdint>
#include <vector>

namespace dronedream_agent_plugin_api
{
struct CapabilityConfiguration
{
  std::string capability_id;
  std::string contract_id;
  std::string authority;
  std::uint32_t deadline_ms{100};
  std::uint32_t startup_deadline_ms{10000};
};

struct CapabilityObservation
{
  std::string contract_id;
  std::uint64_t sequence{0};
  std::int64_t monotonic_time_ns{0};
  bool localization_ok{false};
  bool link_ok{false};
  bool geofence_ok{false};
  double battery_percent{0.0};
};

struct CapabilityProposal
{
  std::string proposal_id;
  std::string command;
  std::string reason;
  bool requires_core_authorization{true};
};

struct CapabilityExecutionReceipt
{
  std::string proposal_id;
  bool accepted{false};
  std::string terminal_status;
  std::vector<std::string> issue_codes;
};

struct CapabilityHealth
{
  bool healthy{false};
  bool deadline_missed{false};
  std::string state;
};

struct CapabilityEvidence
{
  std::string capability_id;
  std::string contract_id;
  std::uint64_t observation_sequence{0};
  std::string terminal_status;
};

class CapabilityPlugin
{
public:
  virtual ~CapabilityPlugin() = default;
  virtual std::string id() const = 0;
  virtual std::string authority() const = 0;
  virtual bool configure(const CapabilityConfiguration & configuration) = 0;
  virtual bool activate() = 0;
  virtual bool observe(const CapabilityObservation & observation) = 0;
  virtual CapabilityProposal propose() = 0;
  virtual CapabilityExecutionReceipt execute(const CapabilityProposal & proposal) = 0;
  virtual CapabilityExecutionReceipt hold(const std::string & reason) noexcept = 0;
  virtual CapabilityHealth health() const noexcept = 0;
  virtual CapabilityEvidence evidence() const noexcept = 0;
  virtual void deactivate() noexcept = 0;
};
}  // namespace dronedream_agent_plugin_api
