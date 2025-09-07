import pandas as pd
import numpy as np

# Create an x series
x = pd.Series(range(101))

# Create y series with different relationships to x
y_linear = x * 100              # Linear relationship
y_potential = x**2              # Potential relationship
y_pot_shifted = (x-50)**2       # Potential relationship
y_pot_3 = -(x-50)**3/20+(1.5*(x-20)**2-2000)       # Potential relationship
y_exponential = np.exp(x / 11)  # Exponential relationship with some noise

# Create a DataFrame
df_kendall = pd.DataFrame({'x': x, 'y_linear': y_linear, 'y_potential': y_potential,
                           'y_pot_shifted': y_pot_shifted, 'y_pot_3': y_pot_3,
                           'y_exponential': y_exponential})

# Calculate Kendall correlation
kendall_corr_linear = df_kendall['x'].corr(df_kendall['y_linear'], method='kendall')
kendall_corr_potential = df_kendall['x'].corr(df_kendall['y_potential'], method='kendall')
kendall_corr_pot_shifted = df_kendall['x'].corr(df_kendall['y_pot_shifted'], method='kendall')
kendall_corr_pot_3 = df_kendall['x'].corr(df_kendall['y_pot_3'], method='kendall')
kendall_corr_exponential = df_kendall['x'].corr(df_kendall['y_exponential'], method='kendall')

import matplotlib.pyplot as plt

plt.figure(figsize=(10, 6))
plt.plot(df_kendall.index, df_kendall['y_linear'], label='y_linear: '+str(kendall_corr_linear))
plt.plot(df_kendall.index, df_kendall['y_potential'], label='y_potential: '+str(kendall_corr_potential))
plt.plot(df_kendall.index, df_kendall['y_pot_shifted'], label='y_pot_shifted: '+str(kendall_corr_pot_shifted))
plt.plot(df_kendall.index, df_kendall['y_pot_3'], label='y_pot_3: '+str(kendall_corr_pot_3))
plt.plot(df_kendall.index, df_kendall['y_exponential'], label='y_exponential: '+str(kendall_corr_exponential))

plt.xlabel('Index')
plt.ylabel('y value')
plt.title('Y Series vs. Index')
plt.legend()
plt.grid(True)
plt.show()