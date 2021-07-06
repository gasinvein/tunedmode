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

if get_option('systemd').enabled()
  conf.set('DBUS_SYSTEMD_SERVICE', 'SystemdService=tunedmode.service')
else
  conf.set('DBUS_SYSTEMD_SERVICE', '')
endif

systemd = dependency('systemd', required: get_option('systemd').enabled())
if get_option('systemd_user_unit_dir') != ''
  user_unit_dir = get_option('systemd_user_unit_dir')
elif systemd.found()
  user_unit_dir = systemd.get_pkgconfig_variable('systemd_user_unit_dir')
else
  user_unit_dir = join_paths(get_option('prefix'), 'lib', 'systemd', 'user')
endif

python.install_sources('tunedmode.py', pure: true)

configure_file(
  input: 'scripts/tunedmode.in',
  output: 'tunedmode',
  configuration: conf,
  install_dir: bindir,
  install_mode: 'rwxr-xr-x'
)

configure_file(
  input: 'data/tunedmode.service.in',
  output: 'tunedmode.service',
  configuration: conf,
  install: get_option('systemd').enabled(),
  install_dir: user_unit_dir,
)

configure_file(
  input: 'data/com.feralinteractive.GameMode.service.in',
  output: 'com.feralinteractive.GameMode.service',
  configuration: conf,
  install: get_option('dbus_activation').enabled(),
  install_dir: join_paths(datadir, 'dbus-1', 'services'),
)
