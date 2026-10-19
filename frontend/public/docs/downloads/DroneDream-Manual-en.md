# 1. DroneDream Overview

DroneDream is a desktop flight workspace that connects natural-language missions, simulation, tuning, laboratory work, and field operations. It was designed so one idea can move from a sentence to a completed drone task without rebuilding the project in separate tools.

## 1.1 Purpose

Drone work is often split across chat windows, map tools, simulators, parameter editors, and live vehicle consoles. DroneDream brings those decisions into one place and keeps the operator focused on the mission.

- Replace scattered tools with one workspace.
- Keep maps, aircraft, and missions connected.
- Let intent guide each flight decision.

## 1.2 Workspaces

Universal provides the complete workspace. SIM, LAB, FIELD, and AGENT focus the interface on simulation, connected hardware, field flight, and natural-language missions while sharing the same account, aircraft, maps, projects, and Runtime.

- Universal connects every DroneDream workspace.
- SIM builds repeatable virtual flights.
- LAB connects sensors and test hardware.
- FIELD prepares and follows real aircraft.
- AGENT turns language into complete missions.

## 1.3 Workflow

Every workflow begins with a goal, turns that goal into explicit settings, runs through the appropriate environment, and returns a result the operator can understand and reuse.

- Describe the outcome in ordinary language.
- Confirm aircraft, location, route, and payload.
- Run the mission in the chosen workspace.
- Follow progress and reuse completed projects.

# 2. Flight Agent

The Flight Agent converts an everyday request into a complete mission. It uses available map locations, aircraft capabilities, payload needs, and current mission state to choose the next useful action.

## 2.1 Mission

State the destination, task, payload, timing, or operating preference in one clear request. The Agent can resolve ordinary building names and practical phrases without requiring coordinates or rigid command syntax.

- Name the place and intended result.
- Add payload or return requirements.
- Mention speed, timing, or route preferences.

## 2.2 Maps

Choose the relevant map before sending the request. The Agent matches named destinations to the map, plans through connected routes, and keeps the mission anchored to recognizable places.

- Select the campus or operating map.
- Use natural building and landmark names.
- Inspect the planned route before starting.

## 2.3 Aircraft and Payload

Select an aircraft whose capabilities match the mission. When a task includes delivery or collection, the payload becomes part of the plan and remains visible throughout the run.

- Confirm the active aircraft and configuration.
- Describe the item being carried or collected.
- Check payload attachment before returning home.

## 2.4 Route and Motion

The Agent uses open straight segments for faster travel and reduces speed before turns, approaches, pickup points, and landing. Control changes are progressive so motion remains continuous instead of jumping between unrelated speeds.

- Cruise faster when the route is clear.
- Slow progressively before corners and approaches.
- Keep moving through small route deviations.
- Stop only when continued flight is impossible.

## 2.5 Live Mission

Start the mission after reviewing its destination and sequence. The live view shows position, route progress, altitude, speed, payload state, return progress, and final landing status.

- Start once the complete plan is ready.
- Follow position, altitude, speed, and payload.
- Switch among available mission camera views.
- Let recoverable deviations continue toward completion.

## 2.6 Return and Reuse

A mission is complete after the requested work, return, and landing have all finished. The completed run remains available so another request can reuse the same aircraft, map, or destination.

- Finish the requested pickup or delivery.
- Return to the selected landing point.
- Confirm landing and final mission status.
- Reuse successful setups for new requests.

# 3. Build and Fly

DroneDream supports the full path from virtual flight behavior to connected hardware and field operation. Each focused workspace exposes the controls needed for that stage while preserving shared project context.

## 3.1 Workspace Choice

Use Universal when work spans several stages. Open SIM for virtual flights, LAB for controlled hardware sessions, FIELD for live vehicle operation, and AGENT for natural-language missions.

- Universal coordinates the complete product family.
- SIM focuses on virtual flight behavior.
- LAB focuses on connected hardware work.
- FIELD focuses on operational aircraft control.
- AGENT focuses on language-driven missions.

## 3.2 Simulation

Choose the PX4 version, airframe, Gazebo vehicle, world, route, environment, and rendering mode. Keep the scenario close to the behavior you want to understand or improve.

- Select the airframe and virtual world.
- Define route, altitude, and starting position.
- Add wind, payload, or sensor conditions.
- Run the complete flight from start to landing.

## 3.3 Tuning

Select the PX4 parameters that should change, set meaningful ranges, choose an optimization method, and define the flight behavior that matters for this project.

- Tune only parameters related to the goal.
- Keep search ranges physically meaningful.
- Balance tracking, speed, and smoothness.
- Compare candidates under consistent scenarios.

## 3.4 Lab Hardware

LAB joins simulation with sensors, controllers, and controlled test equipment. Use it to check communication, calibration, timing, and model behavior before moving to a field aircraft.

- Connect supported sensors and control hardware.
- Confirm streams, units, timing, and calibration.
- Compare measured behavior with the model.
- Save the validated configuration with the project.

## 3.5 Field Flight

FIELD keeps vehicle setup, live telemetry, operator controls, and mission state in one focused view. Confirm the aircraft connection and operating area before beginning the requested work.

- Select the intended aircraft and connection.
- Confirm position, battery, and communication.
- Review route and mission controls together.
- Follow live state through landing completion.

## 3.6 Runtime

DroneDream Runtime supplies local services for PX4, Gazebo, mission execution, and project work. Install it once, let the application manage it, and keep its storage separate from ordinary source files.

- Install Runtime through DroneDream setup.
- Wait until environment preparation finishes.
- Keep the selected installation drive available.
- Recheck Runtime from settings when needed.
