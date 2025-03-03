from parse_receptor import Receptor
from spyrmsd import io, rmsd
import os
import pandas as pd
import numpy as np
import torch
from parse_ligand import Ligand
from torch import sin, cos

def generate_dist(mtx_1, mtx_2):

    """
    Args:
        mtx_1, mtx_2: torch.tensor, shape [n, m, 3], where n is the number of mols, m is the number of atoms in the ligand.

    Returns:
        dist: torch.tensor, shape [n, m, m]
    """

    n, N, C = mtx_1.size()
    n, M, _ = mtx_2.size()
    dist = -2 * torch.matmul(mtx_1, mtx_2.permute(0, 2, 1))
    dist += torch.sum(mtx_1 ** 2, -1).view(-1, N, 1)
    dist += torch.sum(mtx_2 ** 2, -1).view(-1, 1, M)

    dist = (dist >= 0) * dist
    dist = torch.sqrt(dist)

    return dist


def rotation_matrix(alpha: torch.tensor, beta: torch.tensor, gamma: torch.tensor) -> torch.Tensor:
    """
    Args:
        alpha, beta, gamma: torch.tensor, scalar, shape [-1, ]

    Returns:
        R: rotation matrix, torch.tensor, shape [-1, 3, 3]

    """

    alpha = alpha.clone()
    beta = beta.clone()
    gamma = gamma.clone()

    Rx_tensor = torch.cat(((alpha + 1) / (alpha + 1), alpha - alpha, alpha - alpha,
                           alpha - alpha, torch.cos(alpha), - torch.sin(alpha),
                           alpha - alpha, torch.sin(alpha), torch.cos(alpha)), axis=0).reshape(9, -1).T.reshape(-1, 3,
                                                                                                                3)

    Ry_tensor = torch.cat((torch.cos(beta), beta - beta, - torch.sin(beta),
                           beta - beta, (beta + 1) / (beta + 1), beta - beta,
                           torch.sin(beta), beta - beta, torch.cos(beta)), axis=0).reshape(9, -1).T.reshape(-1, 3, 3)

    Rz_tensor = torch.cat((torch.cos(gamma), -torch.sin(gamma), gamma - gamma,
                           torch.sin(gamma), torch.cos(gamma), gamma - gamma,
                           gamma - gamma, gamma - gamma, (gamma + 1) / (gamma + 1)), axis=0).reshape(9, -1).T.reshape(
        -1, 3, 3)

    R = torch.matmul(torch.matmul(Rx_tensor, Ry_tensor), Rz_tensor)

    return R


def rodrigues(vector, theta):
    """
    Args:
        vector: torsion shaft, shape [-1, 3]
        theta: torch.tensor, shape [1, ]

    Returns:
        R_matrix: shape [-1, 3, 3]

    """

    theta = theta.clone()

    a = vector[:, 0]
    b = vector[:, 1]
    c = vector[:, 2]

    R_list = [
        cos(theta) + torch.pow(a, 2) * (1 - cos(theta)).reshape(1, -1),
        a * b * (1 - cos(theta)) - c * sin(theta).reshape(1, -1),
        a * c * (1 - cos(theta)) + b * sin(theta).reshape(1, -1),
        a * b * (1 - cos(theta)) + c * sin(theta).reshape(1, -1),
        cos(theta) + torch.pow(b, 2) * (1 - cos(theta)).reshape(1, -1),
        b * c * (1 - cos(theta)) - a * sin(theta).reshape(1, -1),
        a * c * (1 - cos(theta)) - b * sin(theta).reshape(1, -1),
        b * c * (1 - cos(theta)) + a * sin(theta).reshape(1, -1),
        cos(theta) + torch.pow(c, 2) * (1 - cos(theta)).reshape(1, -1)
    ]

    R_matrix = torch.cat(R_list, axis=0).T.reshape(-1, 3, 3)

    return R_matrix

def vector_length(vector):
    """
    Args:
        vector: torch.tensor, shape [-1, 1, 3]

    Returns:
        vec_length: torch.tensor, shape [-1, 1, 1]
    """
    # print("vector", vector)
    vec_length = torch.sqrt(torch.sum(torch.square(vector), axis=2))  # shape: [-1, 1]
    vec_length = vec_length.reshape(-1, 1, 1)

    return vec_length


def relative_vector_rotation(vector, R):
    """
    Args:
        vector: torch.tensor, shape [-1, 3]
        R: torch.tensor, shape [-1, 3, 3]

    Returns:
        new_vector: torch.tensor, shape [-1, 3]

    """

    num_of_vec = len(vector)
    # R_tensor = R.expand(num_of_vec, 3, 3) # shape [-1, 3, 3]
    R_tensor = R

    vector = vector.reshape(-1, 1, 3)
    vec_length = vector_length(vector)  # shape [-1, 1, 1]
    vector = vector.reshape(-1, 3, 1)  # shape [-1, 1, 3]

    new_vector = torch.matmul(R_tensor, vector).reshape(-1, 1, 3)  # shape [-1, 1, 3]
    new_vec_length = vector_length(new_vector)  # shape [-1, 1, 1]

    # print("new_vector", new_vector)
    new_vector = new_vector * vec_length / new_vec_length  # shape [-1, 1, 3]
    new_vector = new_vector[:, 0, :]  # shape [-1, 3]

    return new_vector


def relative_vector_center_rotation(vector, center, R):
    """
    Args:
        vector: torch.tensor, shape [-1, 3]
        center: torch.tensor, shape [1, ]
        R: torch.tensor, shape [3, 3]

    Returns:
        new_vector: torch.tensor, shape [-1, 3]

    """

    num_of_vec = len(vector)
    R_tensor = R
    center = center.reshape(-1, 1, 3)

    vector = vector.reshape(-1, 1, 3)  # shape [-1, 1, 3]
    vec_length = vector_length(vector)  # shape [-1, 1, 1]

    point_1 = vector
    point_0 = torch.zeros(num_of_vec, 1, 3)  # shape [-1, 1, 3]
    
    new_point_1 = torch.matmul(R_tensor, (point_1 - center).reshape(-1, 3, 1)) + center.reshape(-1, 3, 1)  # shape [-1, 3, 1]
    new_point_0 = torch.matmul(R_tensor, (point_0 - center).reshape(-1, 3, 1)) + center.reshape(-1, 3, 1)  # shape [-1, 3, 1]

    new_vector = (new_point_1 - new_point_0).reshape(-1, 1, 3)  # shape [-1, 1, 3]

    new_vec_length = vector_length(new_vector)  # shape [-1, 1, 1]
    new_vector = new_vector * (vec_length / new_vec_length)  # shape [-1, 1, 3]
    new_vector = new_vector[:, 0, :]  # shape [-1, 3]

    return new_vector

def output_ligand_traj(out_dpath: str,
                       ligand: Ligand):
    """Output the new conformation into the trajectory file.

    Args:
        epoch (int): Epoch number.
        output_path (str): output directory path.
        file_name (str): output trajectory file path.
        origin_heavy_atoms_lines (list): Original heavy atoms lines.
        new_coords (torch.Tensor): predicted ligand atom coordinates.
    """

    origin_heavy_atoms_lines = ligand.origin_heavy_atoms_lines
    new_coords = ligand.pose_heavy_atoms_coords
    poses_file_names = ligand.poses_file_names

    for f_name, coord in zip(poses_file_names, new_coords):
        output_fpath = out_dpath + "/" + f_name + "/optimized_traj.pdb"
        os.makedirs(out_dpath + "/" + f_name, exist_ok=True)

        lines = []
        for num, line in enumerate(origin_heavy_atoms_lines):
            x = coord[num][0].detach().numpy()
            y = coord[num][1].detach().numpy()
            z = coord[num][2].detach().numpy()

            atom_type = line.split()[2]
            pre_element = line.split()[2]
            if pre_element[:2] == "CL":
                element = "Cl"
            elif pre_element[:2] == "BR":
                element = "Br"
            else:
                element = pre_element[0]

            line = "ATOM%7s%5s%4s%2s%4s%12s%8s%8s%6s%6s%12s" % (
                str(num + 1), atom_type, "LIG", "A", "1", "%.3f" % x, "%.3f" % y, "%.3f" % z, "1.00", "0.00", element)
            lines.append(line)

        MODEL_numner = 0
        if not os.path.exists(output_fpath):
            pass
        else:
            with open(output_fpath) as f:
                MODEL_numner = len([x for x in f.readlines() if x[:5] == "MODEL"])

        with open(output_fpath, 'a+') as f:

            f.writelines('MODEL%9s\n' % str(MODEL_numner + 1))

            for line in lines:
                f.writelines(line + '\n')
            f.writelines("TER\n")
            f.writelines("ENDMDL\n")

        with open(out_dpath + "/" + f_name + "/current_pose.pdb", 'w') as f:
            for line in lines:
                f.writelines(line + '\n')


def save_final_lig_cnfr(_condition, out_dpath, ligand):

    poses_file_names = ligand.poses_file_names
    poses_fpath = [os.path.join(out_dpath, x, "final_optimized_cnfr.pdb") for x in poses_file_names]

    origin_heavy_atoms_lines = ligand.origin_heavy_atoms_lines
    new_coords = ligand.pose_heavy_atoms_coords

    _update_index = torch.where(_condition == 1.)[0]
    for index in _update_index:
        index = int(index)

        lines = []
        for num, line in enumerate(origin_heavy_atoms_lines):
            x = new_coords[index][num][0].detach().numpy()
            y = new_coords[index][num][1].detach().numpy()
            z = new_coords[index][num][2].detach().numpy()
        
            atom_type = line.split()[2]
            if atom_type[:2] == "CL":
                element = "Cl"
            elif atom_type[:2] == "BR":
                element = "Br"
            else:
                element = atom_type[0]

            line = "ATOM%7s%5s%4s%2s%4s%12s%8s%8s%6s%6s%12s" % (
                str(num + 1), atom_type, "LIG", "A", "1", "%.3f" % x, "%.3f" % y, "%.3f" % z, "1.00", "0.00", element)
            lines.append(line)

        with open(poses_fpath[index], 'w') as f:
            for line in lines:
                f.writelines(line + '\n')


def save_data(scores_data, out_dpath, ligand):
   
    poses_file_names = ligand.poses_file_names
    poses_fpath = [os.path.join(out_dpath, x, "opt_data.csv") for x in poses_file_names]

    scores_data = np.array(scores_data)
    index = [x for x in range(scores_data.shape[0])]

    steps = len(scores_data)
    for num, f in enumerate(poses_fpath):

        _this_poses_values = []
        for step in range(steps):
            _values = scores_data[step, num, :]
            _this_poses_values.append(_values)
        _this_poses_values = np.array(_this_poses_values)
       
        df = pd.DataFrame(_this_poses_values, index=index, columns=['vina', 'pred_rmsd', 'rmsd+vina'])
        df.to_csv(f)


def save_results(_condition, out_dpath, ligand, scores_data):
    
    poses_file_names = ligand.poses_file_names
    poses_fpath = [os.path.join(out_dpath, x, "final_score.csv") for x in poses_file_names]

    _update_index = torch.where(_condition == 1)[0]
    for index in _update_index:
        index = int(index)

        init_score = scores_data[0][index, :]
        final_score = scores_data[-1][index, :]

        _values = np.array([init_score, final_score])
        df = pd.DataFrame(_values, index=['init', 'final'], columns=['vina', 'pred_rmsd', 'rmsd+vina'])

        df.to_csv(poses_fpath[index])


def cal_hrmsd(ref_mol, out_dpath, ligand):

    poses_file_names = ligand.poses_file_names
    poses_fpath = [os.path.join(out_dpath, x, "current_pose.pdb") for x in poses_file_names]

    try:
        ref = io.loadmol(ref_mol)
        ref.strip()

        coords_ref = ref.coordinates
        anum_ref = ref.atomicnums

        RMSDs = []
        for m in poses_fpath:
            mol = io.loadmol(m)
            mol.strip()

            coord = mol.coordinates
            anum = mol.atomicnums

            RMSD = rmsd.hrmsd(coords_ref, coord, anum_ref, anum, center=False)
            RMSDs.append(RMSD)

        RMSDs = np.array(RMSDs).reshape(-1, 1)

    except Exception as e:
        print("Error:", e)
        RMSDs = np.repeat(np.array(None), len(poses_file_names)).reshape(-1, 1)

    return RMSDs


def local_set_lr(epoch, torsion_param, number_of_frames):
    
    lr_xyz = 0.05
    lr_rotation = 0.05
    lr_torsion = torsion_param / (number_of_frames + 1)

    slope_xyz = (lr_xyz - 0.01) / 50
    slope_rotation = (lr_rotation - 0.01) / 50
    slope_torsion = (lr_torsion - 0.05) / 50

    if epoch > 50:
        epoch = 50

    lr_xyz = lr_xyz - slope_xyz * epoch
    lr_rotation = lr_rotation - slope_rotation * epoch
    lr_torsion = lr_torsion - slope_torsion * epoch

    lr = torch.zeros(6 + number_of_frames)

    for i in range(3):
        lr[i] = lr_xyz

    for i in range(3, 6):
        lr[i] = lr_rotation

    for i in range(6, 6 + number_of_frames):
        lr[i] = lr_torsion

    return lr
