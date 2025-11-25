conda deactivate
conda env remove -n AMBenv
conda create -n AMBenv python=3.10 -y
conda activate AMBenv
conda env update --file environment.yml --prune

pip install -r requirements.txt
pip freeze > requirements.txt

# singal exe
python -m PyInstaller --onefile --windowed --name=HMI_OCR_System --add-data "app;app" --add-data "data;data" --add-data ".env;." app_HW.py

# singal exe with icon --- Make sure your .ico file is high-resolution (256x256 or 128x128)
python -m PyInstaller --onefile --windowed --name=HMI_OCR_System --icon="D:\Shubham\2025\destop app\app\BX.ico" --add-data "app;app" --add-data "data;data" --add-data ".env;." main_desktop_app_enhanced.py"# destop-app" 
