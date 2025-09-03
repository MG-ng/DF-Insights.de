import requests
import pandas as pd
import os

# Replace with the URL of your HDF5 file
url = 'https://df-insights.de/static/data.h5'
file_name = 'downloaded_data.h5'

# Download the file
response = requests.get(url, stream=True)
if response.status_code == 200:
    with open(file_name, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    print(f"File downloaded successfully as {file_name}")

    # Load the HDF5 file into a pandas DataFrame
    try:
        df = pd.read_hdf(file_name)
        print(df.head())
    except Exception as e:
        print(f"Error loading HDF5 file: {e}")
else:
    print(f"Failed to download file. Status code: {response.status_code}")


from typing import Literal, get_args
from pickle import TRUE
import matplotlib.pyplot as plt
import seaborn as sns
import os

year = 2024

for method in get_args( Literal["pearson", "kendall", "spearman"] ):
  # Create the Pearson correlation matrix
  matrix = df.corr(method=method)

  # Create a directory for plots if it doesn't exist
  if not os.path.exists('plots'):
      os.makedirs('plots')

  # Visualize the correlation matrix as a heatmap
  name = "All-" + method + str(year)
  plt.figure(figsize=(42, 40))  # Width, height in inches
  sns.heatmap(matrix, annot=True, cmap="coolwarm", fmt=".2f", center=0, linewidths=0.5)
  plt.savefig( f"plots/plot{name}.jpg",
                          dpi = 90,
                          bbox_inches = 'tight',  # Remove extra whitespace
                          format = 'jpg' )  # File format
  plt.close()  # Free memory

  print(f"Correlation heatmap saved to plots/plot{name}.jpg")

