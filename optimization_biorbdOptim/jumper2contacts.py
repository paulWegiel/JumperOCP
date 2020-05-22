import biorbd

from biorbd_optim import (
    Instant,
    OptimalControlProgram,
    Constraint,
    Objective,
    ProblemType,
    BidirectionalMapping,
    Mapping,
    Bounds,
    QAndQDotBounds,
    InitialConditions,
    ShowResult,
)


def custom_func_2c_to_1c_transition(ocp, nlp, t, x, u,):
    val = ocp.nlp[0]["contact_forces_func"](x[0], u[0])[[2, 5], 0]
    return val

def custom_func_1c_to_0c_transition(ocp, nlp, t, x, u,):
    val = nlp["contact_forces_func"](x[-1], u[-1])[:, 0]
    return val

def custom_func_anatomical_constraint(ocp, nlp, t, x, u,):
    val = x[0][7:14]
    return val

def prepare_ocp(
    model_path, phase_time, number_shooting_points, use_symmetry=True,
):
    # --- Options --- #
    # Model path
    biorbd_model = [biorbd.Model(elt) for elt in model_path]

    nb_phases = len(biorbd_model)
    torque_activation_min, torque_activation_max, torque_activation_init = -1, 1, 0

    if use_symmetry:
        q_mapping = BidirectionalMapping(
            Mapping([0, 1, 2, -1, 3, -1, 3, 4, 5, 6, 4, 5, 6], [5]), Mapping([0, 1, 2, 4, 7, 8, 9])
        )
        q_mapping = q_mapping, q_mapping, q_mapping
        tau_mapping = BidirectionalMapping(
            Mapping([-1, -1, -1, -1, 0, -1, 0, 1, 2, 3, 1, 2, 3], [5]), Mapping([4, 7, 8, 9])
        )
        tau_mapping = tau_mapping, tau_mapping, tau_mapping

    else:
        q_mapping = BidirectionalMapping(
            Mapping([i for i in range(biorbd_model[0].nbQ())]), Mapping([i for i in range(biorbd_model[0].nbQ())]),
        )
        q_mapping = q_mapping, q_mapping, q_mapping
        tau_mapping = q_mapping

    # Add objective functions
    objective_functions = (
        (),
        (
            {"type": Objective.Mayer.MINIMIZE_PREDICTED_COM_HEIGHT, "weight": -1},
            {"type": Objective.Lagrange.MINIMIZE_TORQUE, "weight": 1 / 100},
        ),
        (
            {"type": Objective.Lagrange.MINIMIZE_TORQUE, "weight": 1 / 100},
        ),
    )

    # Dynamics
    # problem_type = (
    #     ProblemType.torque_driven_with_contact,
    #     ProblemType.torque_driven_with_contact,
    # )
    problem_type = (
        ProblemType.torque_activations_driven_with_contact,
        ProblemType.torque_activations_driven_with_contact,
        ProblemType.torque_activations_driven,

    )

    constraints_first_phase = []
    constraints_second_phase = []
    constraints_third_phase = []

    contact_axes = (1, 2, 4, 5)
    for i in contact_axes:
        constraints_first_phase.append(
            {
                "type": Constraint.CONTACT_FORCE_INEQUALITY,
                "direction": "GREATER_THAN",
                "instant": Instant.ALL,
                "contact_force_idx": i,
                "boundary": 0,
            }
        )
    contact_axes = (1, 3)
    for i in contact_axes:
        constraints_second_phase.append(
            {
                "type": Constraint.CONTACT_FORCE_INEQUALITY,
                "direction": "GREATER_THAN",
                "instant": Instant.ALL,
                "contact_force_idx": i,
                "boundary": 0,
            }
        )
    constraints_first_phase.append(
        {
            "type": Constraint.NON_SLIPPING,
            "instant": Instant.ALL,
            "normal_component_idx": (1, 2),
            "tangential_component_idx": 0,
            "static_friction_coefficient": 0.5,
        }
    )
    constraints_second_phase.append(
        {
            "type": Constraint.NON_SLIPPING,
            "instant": Instant.ALL,
            "normal_component_idx": 1,
            "tangential_component_idx": 0,
            "static_friction_coefficient": 0.5,
        }
    )
    constraints_second_phase.append(
        {
            "type": Constraint.CUSTOM,
            "function": custom_func_2c_to_1c_transition,
            "instant": Instant.START,
        }
    )
    # constraints_second_phase.append(
    #     {
    #         "type": Constraint.CUSTOM,
    #         "function": custom_func_anatomical_constraint,
    #         "instant": Instant.END,
    #     }
    # )
    if not use_symmetry:
        first_dof = (3, 4, 7, 8, 9)
        second_dof = (5, 6, 10, 11, 12)
        coeff = (-1, 1, 1, 1, 1)
        for i in range(len(first_dof)):
            constraints_first_phase.append(
                {
                    "type": Constraint.PROPORTIONAL_STATE,
                    "instant": Instant.ALL,
                    "first_dof": first_dof[i],
                    "second_dof": second_dof[i],
                    "coef": coeff[i],
                }
            )

        for i in range(len(first_dof)):
            constraints_second_phase.append(
                {
                    "type": Constraint.PROPORTIONAL_STATE,
                    "instant": Instant.ALL,
                    "first_dof": first_dof[i],
                    "second_dof": second_dof[i],
                    "coef": coeff[i],
                }
            )
    constraints = (constraints_first_phase, constraints_second_phase, constraints_third_phase)

    # Path constraint
    if use_symmetry:
        nb_q = q_mapping[0].reduce.len
        nb_qdot = nb_q
        pose_at_first_node = [0, 0, -0.5336, 1.4, 0.8, -0.9, 0.47]
    else:
        nb_q = q_mapping[0].reduce.len
        nb_qdot = nb_q
        pose_at_first_node = [
            0,
            0,
            -0.5336,
            0,
            1.4,
            0,
            1.4,
            0.8,
            -0.9,
            0.47,
            0.8,
            -0.9,
            0.47,
        ]

    # Initialize X_bounds
    X_bounds = [QAndQDotBounds(biorbd_model[i], all_generalized_mapping=q_mapping[i]) for i in range(nb_phases)]
    X_bounds[0].min[:, 0] = pose_at_first_node + [0] * nb_qdot
    X_bounds[0].max[:, 0] = pose_at_first_node + [0] * nb_qdot

    # Initial guess
    X_init = [
        InitialConditions(pose_at_first_node + [0] * nb_qdot),
        InitialConditions(pose_at_first_node + [0] * nb_qdot),
        InitialConditions(pose_at_first_node + [0] * nb_qdot),

    ]

    # Define control path constraint
    U_bounds = [
        Bounds(min_bound=[torque_activation_min] * tau_m.reduce.len, max_bound=[torque_activation_max] * tau_m.reduce.len)
        for tau_m in tau_mapping
    ]

    U_init = [InitialConditions([torque_activation_init] * tau_m.reduce.len) for tau_m in tau_mapping]
    # ------------- #

    return OptimalControlProgram(
        biorbd_model,
        problem_type,
        number_shooting_points,
        phase_time,
        X_init,
        U_init,
        X_bounds,
        U_bounds,
        objective_functions=objective_functions,
        constraints=constraints,
        q_mapping=q_mapping,
        q_dot_mapping=q_mapping,
        tau_mapping=tau_mapping,
    )


def run_and_save_ocp(model_path, phase_time, number_shooting_points):
    ocp = prepare_ocp(
        model_path=model_path,
        phase_time=phase_time,
        number_shooting_points=number_shooting_points,
        use_symmetry=True,
    )
    # sol = ocp.solve(options_ipopt={"max_iter": 5}, show_online_optim=True)
    sol = ocp.solve(options_ipopt={"hessian_approximation": "limited-memory"}, show_online_optim=True)

    OptimalControlProgram.save(ocp, sol, "../Results/jumper2contacts_sol")


if __name__ == "__main__":
    model_path = ("../models/jumper2contacts.bioMod", "../models/jumper1contacts.bioMod", "../models/jumper1contacts.bioMod")
    phase_time = [0.4, 0.2, 2]
    number_shooting_points = [6, 6, 6]

    run_and_save_ocp(model_path, phase_time=phase_time, number_shooting_points=number_shooting_points)
    ocp, sol = OptimalControlProgram.load("../Results/jumper2contacts_sol.bo")

    # ocp = prepare_ocp(model_path=model_path, phase_time=phase_time, number_shooting_points=number_shooting_points, use_symmetry=True)
    # sol = ocp.solve(options_ipopt={"hessian_approximation": "limited-memory"}, show_online_optim=True)


    # --- Show results --- #
    result = ShowResult(ocp, sol)
    result.graphs()
    result.animate(nb_frames=150)
