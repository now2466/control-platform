from setuptools import setup

package_name = "pinky_control_watchdog"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    entry_points={
        "console_scripts": [
            "manual_velocity_watchdog = pinky_control_watchdog.manual_velocity_watchdog:main",
        ],
    },
)
