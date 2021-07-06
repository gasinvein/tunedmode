project('tunedmode')

pymod = import('python')
python = pymod.find_installation('python3', modules: [
          'gi',
          'dbus',
          'psutil',
          'xdg'
        ])

bindir = join_paths(get_option('prefix'), get_option('bindir'))
datadir = join_paths(get_option('prefix'), get_option('datadir'))

conf = configuration_data()
conf.set('bindir', bindir)

python.install_sources('tunedmode.py', pure: true)

configure_file(
  input: 'scripts/tunedmode.in',
  output: 'tunedmode',
  configuration: conf,
  install_dir: bindir,
  install_mode: 'rwxr-xr-x'
)

configure_file(
  input: 'data/com.feralinteractive.GameMode.service.in',
  output: 'com.feralinteractive.GameMode.service',
  configuration: conf,
  install_dir: join_paths(datadir, 'dbus-1', 'services')
)
