import xdesign
from xdesign.grid import *
from xdesign.material import Material
import numpy as np
import matplotlib.pyplot as plt
from xdesign.plot import *
import vtk
from mpl_toolkits.mplot3d import Axes3D
import matplotlib as mpl
import dxchange
np.set_printoptions(threshold=np.inf)


protein = Material('H48.6C32.9N8.9O8.9S0.6', 1.35)
epoxy = Material('C2H4O', 1.25)

print 'protein: ', protein.refractive_index_delta(20)
print 'epoxy: ', epoxy.refractive_index_delta(20)

grid = Grid3d([64, 64, 64], [1, 1, 1], epoxy, 20)
grid = grid.add_sphere([32, 0, 0], 16, protein)
grid = grid.add_cylinder((0, 0, 0), 50, 0, 0, 5, epoxy)

data_matrix = (grid.grid_delta * 1e9).astype('uint16')

# print data_matrix[32, :, :]
# plt.contour(data_matrix[32, :, :])
# plt.show()

