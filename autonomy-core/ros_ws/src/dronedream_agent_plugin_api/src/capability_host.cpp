#include "dronedream_agent_plugin_api/capability_plugin.hpp"
#include "dronedream_agent_msgs/msg/mission_lifecycle.hpp"
#include "dronedream_agent_msgs/msg/mission_observation.hpp"
#include "dronedream_agent_msgs/msg/safety_event.hpp"

#include <lifecycle_msgs/msg/state.hpp>
#include <iostream>
#include <memory>
#include <pluginlib/class_loader.hpp>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp_lifecycle/lifecycle_node.hpp>
#include <string>
#include <stdexcept>
#include <vector>
#include <chrono>

using CallbackReturn = rclcpp_lifecycle::node_interfaces::LifecycleNodeInterface::CallbackReturn;

class CapabilityHost final : public rclcpp_lifecycle::LifecycleNode
{
public:
  CapabilityHost()
  : rclcpp_lifecycle::LifecycleNode("dronedream_capability_host")
  {
    declare_parameter<std::vector<std::string>>(
      "plugins", {"dronedream_agent_plugin_api/SafeHoldCapability"});
    declare_parameter<std::string>("contract_id", "runtime-probe-contract");
    declare_parameter<int>("watchdog_deadline_ms", 100);
    declare_parameter<int>("watchdog_startup_deadline_ms", 10000);
    declare_parameter<std::string>("observation_topic", "/dronedream/mission_observation");
    declare_parameter<std::string>("lifecycle_topic", "/dronedream/mission_lifecycle");
    declare_parameter<std::string>("safety_event_topic", "/dronedream/safety_event");
  }

  CallbackReturn on_configure(const rclcpp_lifecycle::State &) override
  {
    try {
      loader_ = std::make_unique<Loader>(
        "dronedream_agent_plugin_api",
        "dronedream_agent_plugin_api::CapabilityPlugin");
      const auto plugin_names = get_parameter("plugins").as_string_array();
      for (const auto & name : plugin_names) {
        auto plugin = loader_->createSharedInstance(name);
        dronedream_agent_plugin_api::CapabilityConfiguration configuration{
          plugin->id(), get_parameter("contract_id").as_string(), plugin->authority(),
          static_cast<std::uint32_t>(get_parameter("watchdog_deadline_ms").as_int()),
          static_cast<std::uint32_t>(
            get_parameter("watchdog_startup_deadline_ms").as_int())};
        if (!plugin->configure(configuration)) {
          throw std::runtime_error("plugin rejected typed configuration");
        }
        plugins_.push_back(plugin);
      }
      safety_publisher_ = create_publisher<dronedream_agent_msgs::msg::SafetyEvent>(
        get_parameter("safety_event_topic").as_string(), rclcpp::QoS(20).reliable());
      observation_subscription_ =
        create_subscription<dronedream_agent_msgs::msg::MissionObservation>(
        get_parameter("observation_topic").as_string(), rclcpp::SensorDataQoS(),
        [this](const dronedream_agent_msgs::msg::MissionObservation::SharedPtr message) {
          if (failed_closed_ || stopping_ || !rclcpp::ok()) {
            return;
          }
          const auto monotonic_time = std::chrono::steady_clock::now().time_since_epoch();
          dronedream_agent_plugin_api::CapabilityObservation observation{
            message->contract_id,
            message->sequence,
            std::chrono::duration_cast<std::chrono::nanoseconds>(monotonic_time).count(),
            message->localization_ok,
            message->link_ok,
            message->geofence_ok,
            static_cast<double>(message->battery_percent)};
          for (const auto & plugin : plugins_) {
            if (!plugin->observe(observation)) {
              fail_closed(plugin, "OBSERVATION_REJECTED");
              return;
            }
          }
        });
      lifecycle_subscription_ =
        create_subscription<dronedream_agent_msgs::msg::MissionLifecycle>(
        get_parameter("lifecycle_topic").as_string(), rclcpp::QoS(10).reliable(),
        [this](const dronedream_agent_msgs::msg::MissionLifecycle::SharedPtr message) {
          if (
            message->contract_id != get_parameter("contract_id").as_string() ||
            message->terminal_state != "ON_GROUND" || message->executor_return_code != 0 ||
            !message->landing_confirmed || !message->safe_to_stop_watchdog)
          {
            return;
          }
          stopping_ = true;
          watchdog_.reset();
          RCLCPP_INFO(
            get_logger(), "accepted core terminal lifecycle event for contract %s",
            message->contract_id.c_str());
        });
      return plugins_.empty() ? CallbackReturn::FAILURE : CallbackReturn::SUCCESS;
    } catch (const std::exception & error) {
      RCLCPP_ERROR(get_logger(), "plugin configure failed: %s", error.what());
      plugins_.clear();
      loader_.reset();
      return CallbackReturn::FAILURE;
    }
  }

  CallbackReturn on_activate(const rclcpp_lifecycle::State &) override
  {
    stopping_ = false;
    for (const auto & plugin : plugins_) {
      if (!plugin->activate() || !plugin->health().healthy) {
        deactivate_all();
        return CallbackReturn::FAILURE;
      }
      RCLCPP_INFO(get_logger(), "activated plugin %s", plugin->id().c_str());
    }
    watchdog_ = create_wall_timer(std::chrono::milliseconds(25), [this]() {
      // SIGINT/SIGTERM makes rclcpp::ok() false before spin() returns.  Ignore
      // that orderly teardown window: observations have intentionally stopped,
      // so treating the resulting stale health report as an in-flight deadline
      // miss would publish a false emergency after a successful landing.
      if (stopping_ || !rclcpp::ok()) {
        return;
      }
      for (const auto & plugin : plugins_) {
        const auto report = plugin->health();
        if (!report.healthy || report.deadline_missed) {
          fail_closed(plugin, "WATCHDOG_HEALTH_OR_DEADLINE_FAILURE");
          return;
        }
      }
    });
    return CallbackReturn::SUCCESS;
  }

  CallbackReturn on_deactivate(const rclcpp_lifecycle::State &) override
  {
    stopping_ = true;
    watchdog_.reset();
    deactivate_all();
    return CallbackReturn::SUCCESS;
  }

  CallbackReturn on_cleanup(const rclcpp_lifecycle::State &) override
  {
    stopping_ = true;
    watchdog_.reset();
    deactivate_all();
    plugins_.clear();
    observation_subscription_.reset();
    lifecycle_subscription_.reset();
    safety_publisher_.reset();
    loader_.reset();
    return CallbackReturn::SUCCESS;
  }

  ~CapabilityHost() override {deactivate_all();}

private:
  using Plugin = dronedream_agent_plugin_api::CapabilityPlugin;
  using Loader = pluginlib::ClassLoader<Plugin>;

  void deactivate_all() noexcept
  {
    for (const auto & plugin : plugins_) {
      plugin->deactivate();
    }
  }

  void fail_closed(const std::shared_ptr<Plugin> & plugin, const std::string & issue)
  {
    if (failed_closed_) {
      return;
    }
    failed_closed_ = true;
    const auto receipt = plugin->hold(issue);
    if (safety_publisher_) {
      dronedream_agent_msgs::msg::SafetyEvent event;
      event.header.stamp = now();
      event.contract_id = get_parameter("contract_id").as_string();
      event.observation_sequence = plugin->evidence().observation_sequence;
      event.severity = 3;
      event.action = "safe_hold_then_land";
      event.issue_codes = receipt.issue_codes;
      safety_publisher_->publish(event);
    }
    deactivate_all();
    watchdog_.reset();
    RCLCPP_FATAL(get_logger(), "runtime plugin watchdog forced fail-closed hold: %s", issue.c_str());
  }

  std::unique_ptr<Loader> loader_;
  std::vector<std::shared_ptr<Plugin>> plugins_;
  rclcpp::TimerBase::SharedPtr watchdog_;
  rclcpp::Subscription<dronedream_agent_msgs::msg::MissionObservation>::SharedPtr
    observation_subscription_;
  rclcpp::Subscription<dronedream_agent_msgs::msg::MissionLifecycle>::SharedPtr
    lifecycle_subscription_;
  rclcpp::Publisher<dronedream_agent_msgs::msg::SafetyEvent>::SharedPtr safety_publisher_;
  bool failed_closed_{false};
  bool stopping_{false};
};

int main(int argc, char ** argv)
{
  const bool self_test = argc == 2 && std::string(argv[1]) == "--self-test";
  const int ros_argc = self_test ? 1 : argc;
  rclcpp::init(ros_argc, argv);
  auto node = std::make_shared<CapabilityHost>();
  node->configure();
  if (node->get_current_state().id() != lifecycle_msgs::msg::State::PRIMARY_STATE_INACTIVE) {
    rclcpp::shutdown();
    return 2;
  }
  node->activate();
  if (node->get_current_state().id() != lifecycle_msgs::msg::State::PRIMARY_STATE_ACTIVE) {
    rclcpp::shutdown();
    return 3;
  }
  if (self_test) {
    node->deactivate();
    node->cleanup();
    std::cout << "PLUGIN_LIFECYCLE_READY configure=ok activate=ok deactivate=ok cleanup=ok"
              << std::endl;
    rclcpp::shutdown();
    return 0;
  }
  rclcpp::spin(node->get_node_base_interface());
  node->deactivate();
  node->cleanup();
  rclcpp::shutdown();
  return 0;
}
