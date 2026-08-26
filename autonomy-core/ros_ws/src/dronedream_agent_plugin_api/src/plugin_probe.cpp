#include "dronedream_agent_plugin_api/capability_plugin.hpp"

#include <iostream>
#include <memory>
#include <pluginlib/class_loader.hpp>

int main()
{
  pluginlib::ClassLoader<dronedream_agent_plugin_api::CapabilityPlugin> loader(
    "dronedream_agent_plugin_api",
    "dronedream_agent_plugin_api::CapabilityPlugin");
  auto plugin = loader.createSharedInstance(
    "dronedream_agent_plugin_api/SafeHoldCapability");
  dronedream_agent_plugin_api::CapabilityConfiguration configuration{
    plugin->id(), "probe-contract", plugin->authority(), 100};
  if (!plugin->configure(configuration) || !plugin->activate() || !plugin->health().healthy) {
    return 2;
  }
  dronedream_agent_plugin_api::CapabilityObservation observation{
    "probe-contract", 1, 1, true, true, true, 100.0};
  if (!plugin->observe(observation)) {
    return 4;
  }
  const auto proposal = plugin->propose();
  const auto execution = plugin->execute(proposal);
  const auto evidence = plugin->evidence();
  if (!execution.accepted || evidence.observation_sequence != 1) {
    return 5;
  }
  std::cout << "PLUGIN_PROBE_READY id=" << plugin->id()
            << " authority=" << plugin->authority()
            << " abi=configure,observe,propose,execute,hold,health,evidence" << std::endl;
  plugin->deactivate();
  return plugin->health().healthy ? 3 : 0;
}
