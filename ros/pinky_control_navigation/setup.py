from setuptools import find_packages, setup

package_name = "pinky_control_navigation"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", ["launch/robot_nav2.launch.py"]),
        (f"share/{package_name}/map", ["map/map_260905.yaml", "map/map_260905.pgm"]),
        (f"share/{package_name}/params", ["params/nav2_params.yaml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    entry_points={
        "console_scripts": [
            "nav2_lifecycle_gate = pinky_control_navigation.nav2_lifecycle_gate:main",
        ],
    },
)
