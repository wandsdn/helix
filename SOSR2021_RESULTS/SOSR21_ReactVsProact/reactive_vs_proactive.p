set datafile separator ','
set autoscale
unset log
unset key
set ylabel 'Recovery Time (ms)' offset 3.0,0
set yrange [0:100]
set bmargin 1.5
set lmargin 4.5
set rmargin 1
set tmargin 0.5

set terminal svg size 644,250 enhanced background rgb 'white' font ',Linux Libertine O,18'
set output 'reactive_vs_proactive.svg'


set key at 6.25,100 box samplen 0.5 spacing 1 vertical maxrow 1

set boxwidth 1
set style fill pattern 0
set ytics 20 offset 0.5,0 nomirror scale 1
set xtics offset 0,0.5 nomirror scale 0

#set style histogram gap 1

set offset -0.4,-0.4,0,0
plot 'reactive_vs_proactive.dat' using 2:xticlabels(1) with histograms ls 1 title "React 20ms",\
     'reactive_vs_proactive.dat' using 3:xticlabels(1) with histograms ls 2 title "React 4ms", \
     'reactive_vs_proactive.dat' using 4:xticlabels(1) with histograms ls 3 title "Helix", \
     '' u ($0-0):($2 + 6):2 with labels notitle, \
     '' u ($0+0.20):($3 + 10):3 with labels notitle, \
     '' u ($0+0.40):($4 + 6):4 with labels notitle
