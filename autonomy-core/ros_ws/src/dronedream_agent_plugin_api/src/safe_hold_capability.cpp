#include "dronedream_agent_plugin_api/capability_plugin.hpp"

#include <chrono>
#include <pluginlib/class_list_macros.hpp>

namespace dronedream_agent_plugin_api
{
class SafeHoldCapability final : public CapabilityPlugin
{
public:
  std::string id() const override {return "runtime.safe-hold";}
  std::string authority() const override {return "control-policy";}
  bool configure(const CapabilityConfiguration & configuration) override
  {
    configuration_ = configuration;
    configured_ = !configuration.contract_id.empty() && configuration.deadline_ms > 0 &&
      configuration.startup_deadline_ms >= configuration.deadline_ms;
    return configured_;
  }
  bool activate() override
  {
    active_ = configured_;
    last_observation_ = std::chrono::steady_clock::now();
    return active_;
  }
  bool observe(const CapabilityObservation & observation) override
  {
    if (!active_ || observation.contract_id != configuration_.contract_id) {
      return false;
    }
    observation_ = observation;
    last_observation_ = std::chrono::steady_clock::now();
    has_observation_ = true;
    return true;
  }
  CapabilityProposal propose() override
  {
    return CapabilityProposal{
      "safe-hold-" + std::to_string(observation_.sequence),
      "safe_hold",
      "Certified runtime capability proposes zero-velocity hold.",
      true};
  }
  CapabilityExecutionReceipt execute(const CapabilityProposal & proposal) override
  {
    if (!active_ || proposal.command != "safe_hold" || !proposal.requires_core_authorization) {
      return CapabilityExecutionReceipt{
        proposal.proposal_id, false, "rejected", {"CORE_AUTHORIZATION_REQUIRED"}};
    }
    holding_ = true;
    return CapabilityExecutionReceipt{proposal.proposal_id, true, "holding", {}};
  }
  CapabilityExecutionReceipt hold(const std::string & reason) noexcept override
  {
    holding_ = active_;
    return CapabilityExecutionReceipt{
      "watchdog-hold", active_, active_ ? "holding" : "inactive", {reason}};
  }
  CapabilityHealth health() const noexcept override
  {
    const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::steady_clock::now() - last_observation_).count();
    const auto limit = has_observation_ ? configuration_.deadline_ms :
      configuration_.startup_deadline_ms;
    const bool missed = active_ && elapsed > limit;
    return CapabilityHealth{
      active_ && !missed,
      missed,
      holding_ ? "holding" : (missed ? "deadline-missed" : (active_ ? "active" : "inactive"))};
  }
  CapabilityEvidence evidence() const noexcept override
  {
    return CapabilityEvidence{
      id(), configuration_.contract_id, observation_.sequence,
      holding_ ? "holding" : (active_ ? "active" : "inactive")};
  }
  void deactivate() noexcept override {active_ = false;}

private:
  CapabilityConfiguration configuration_{};
  CapabilityObservation observation_{};
  bool configured_{false};
  bool active_{false};
  bool holding_{false};
  bool has_observation_{false};
  std::chrono::steady_clock::time_point last_observation_{};
};
}  // namespace dronedream_agent_plugin_api

PLUGINLIB_EXPORT_CLASS(
  dronedream_agent_plugin_api::SafeHoldCapability,
  dronedream_agent_plugin_api::CapabilityPlugin)
