import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const out = path.dirname(fileURLToPath(import.meta.url));
const data = JSON.parse(await fs.readFile(path.join(out, 'measurements.json'), 'utf8'));
const wb = Workbook.create();
const params = wb.worksheets.add('参数标定');
const source = wb.worksheets.add('图像测量');
const ink = '#24364B', input = '#FFF2CC', calc = '#EAF1F8';
const parameterRows = new Map();
const resultRows = new Map();

/** Write a typed scalar or a spreadsheet formula. */
function put(sheet, address, value) {
  const cell = sheet.getRange(address);
  if (typeof value === 'string' && value.startsWith('=')) cell.formulas = [[value]];
  else cell.values = [[value]];
}

/** Apply consistent legible formatting to a bounded worksheet. */
function base(sheet, last, widths) {
  sheet.showGridLines = false;
  sheet.getRange(`A1:H${last}`).format.font = {name: 'Microsoft YaHei', size: 10, color: ink};
  sheet.getRange(`A1:H${last}`).format.rowHeight = 24;
  sheet.getRange(`A1:H${last}`).format.verticalAlignment = 'center';
  widths.forEach((width, index) => {
    sheet.getRange(`${String.fromCharCode(65+index)}1:${String.fromCharCode(65+index)}${last}`).format.columnWidthPx = width;
  });
  sheet.getRange('A2').format.font = {name:'Microsoft YaHei', size:16, bold:true, color:ink};
}

/** Format a table's header without adding a full cell grid. */
function header(sheet, range) {
  sheet.getRange(range).format = {fill:ink, font:{color:'#FFFFFF',bold:true},
    rowHeight:28, horizontalAlignment:'center', verticalAlignment:'center'};
}

/** Add a parameter, preserving the source value separately from editable proposals. */
function parameter(name, current, proposed, unit, status, rationale) {
  const row = 6 + parameterRows.size;
  parameterRows.set(name, row);
  params.getRange(`A${row}:E${row}`).values = [[name,current,null,unit,status]];
  put(params, `C${row}`, proposed);
  put(params, `G${row}`, rationale);
  params.getRange(`C${row}`).format.fill = typeof proposed === 'string' && proposed.startsWith('=') ? calc : input;
  params.getRange(`G${row}`).format.wrapText = true;
  params.getRange(`A${row}:H${row}`).format.rowHeight = 36;
}

/** Reference a proposed parameter value. */
function p(name) { return `$C$${parameterRows.get(name)}`; }

/** Add an explanatory derived quantity below the parameter register. */
function result(name, formula, unit, explanation) {
  const row = 49 + resultRows.size;
  resultRows.set(name,row);
  params.getRange(`A${row}:E${row}`).values = [[name,null,null,unit,'公式计算']];
  put(params, `C${row}`, formula);
  put(params, `G${row}`, explanation);
  params.getRange(`C${row}`).format.fill = calc;
  params.getRange(`G${row}`).format.wrapText = true;
  params.getRange(`A${row}:H${row}`).format.rowHeight = 34;
}

/** Reference one of the derived geometry quantities. */
function r(name) { return `$C$${resultRows.get(name)}`; }

base(params, 94, [268,94,120,65,144,18,540,15]);
base(source, 290, [170,88,90,90,94,94,88,252]);
params.tabColor = ink;
source.tabColor = '#6687A7';
put(params, 'A2', 'main.py 图像参数标定');
put(params, 'A3', '黄色为可改初值，蓝色为公式。Target_Y 由“图像测量”B22 的理想位置确认项控制。');
put(params, 'A4', '单张叠加 JPEG 的离线估计，尚未板端验证。动态门限保留现值，不视为已标定。');
params.getRange('A5:E5').values = [['参数 / 分量','源码当前值','建议 / 条件值','单位','结论类型']];
put(params, 'G5', '依据与使用条件');
header(params, 'A5:E5');

put(source, 'A2', '图像测量与计算依据');
put(source, 'A3', '来源：pictures/20260924163412.jpeg；参数快照：code/main.py（2026-09-24）。');
source.getRange('A5:D5').values = [['输入 / 测量项','数值','单位','类型']];
header(source, 'A5:D5');
const observations = [
 ['图像宽度',data.size[0],'px','图像元数据'],
 ['图像高度',data.size[1],'px','图像元数据'],
 ['横线中心拟合斜率','=SLOPE(D58:D290,A58:A290)','px/px','离线拟合'],
 ['横线拟合截距','=INTERCEPT(D58:D290,A58:A290)','px','离线拟合'],
 ['采样列数','=COUNT(A58:A290)','列','图像统计'],
 ['可见上缘中位数','=MEDIAN(B58:B290)','px','图像统计'],
 ['可见下缘中位数','=MEDIAN(C58:C290)','px','图像统计'],
 ['几何估计误差约',2,'px','经验估计'],
 ['竖线左界约',179,'px','图像估计'],
 ['竖线右界约（含）',198,'px','图像估计'],
 ['竖线可见顶部',0,'px','被画幅截断'],
 ['竖线可见底部约',67,'px','接入横线'],
 ['裁剪附加余量',5,'px','建议初值'],
 ['交点距离附加余量',4,'px','建议初值'],
 ['LAB 亮度上界余量',5,'L','建议初值'],
 ['LAB 色度边界余量',3,'a/b','建议初值'],
 ['照片为理想巡线位置','未确认','是/否','需用户确认'],
];
observations.forEach((row, index) => {
  const n=index+6;
  source.getRange(`A${n}:D${n}`).values=[[row[0],null,row[2],row[3]]];
  put(source,`B${n}`,row[1]);
  source.getRange(`B${n}`).format.fill=typeof row[1]==='string'&&row[1].startsWith('=')?calc:input;
});
source.getRange('B22').dataValidation = {rule:{type:'list',values:['未确认','是','否']}};
source.getRange('B8:B9').setNumberFormat('0.000000');
const photo = await fs.readFile(path.resolve(out,'../../pictures/20260924163412.jpeg'));
source.images.add({dataUrl:`data:image/jpeg;base64,${photo.toString('base64')}`,
  anchor:{from:{row:4,col:4},extent:{widthPx:400,heightPx:300}}});
put(source,'E19','坐标原点：左上，x 向右，y 向下。');
put(source,'E20','原图含彩框和文字，不能当作相机原始帧。');
put(source,'E21','横线下缘受 y≈82 的叠加线遮挡，中心约 ±2 px。');
put(source,'E22','竖线顶部在图外，测得的是可见长度。');
put(source,'A24','方法：先用 5×5 二项核近似高斯滤波，再将 sRGB 转为 D65 CIELAB。');
put(source,'A25','色彩样本避开彩框和接头。阈值只覆盖本图样本，MaixPy 量化及现场光照仍需复核。');
put(source,'A26','几何：x=25…168、207…295，y=66…81，L<56 的首末可见像素中点作最小二乘拟合。');
put(source,'A27','这不是 MaixPy robust 回归输出。修改采样坐标不会重新读图；更换照片需重新提取样本。');

source.getRange('A29:H29').values=[['样本区域','通道','最小值','最大值','P05','P95','像素数','采样框 [x0,y0,x1,y1)']];
header(source,'A29:H29');
const channelRows={L:[],A:[],B:[]};
data.samples.forEach((sample,index)=>{
  ['L','A','B'].forEach((channel,ch)=>{
    const row=30+index*3+ch;
    source.getRange(`A${row}:H${row}`).values=[[sample.label,channel,sample.minimum[ch],sample.maximum[ch],
      sample.p05[ch],sample.p95[ch],sample.n,`[${sample.box.join(', ')}]`]];
    if(index<4) channelRows[channel].push(row);
  });
});
source.getRange('C30:F50').setNumberFormat('0.00');
source.tables.add('A29:H50',true,'LabSamples');
put(source,'A52','色彩换算：https://docs.opencv.org/4.x/de/d25/imgproc_color_conversions.html');
put(source,'A53','阈值与回归接口：https://wiki.sipeed.com/maixpy/api/maix/image.html');
put(source,'A54','连通分量：8 邻域；闭运算后开运算。未复现 MaixPy margin=2 合并或固件回归实现。');
put(source,'A55','以下是保留的逐列边界读数。中心列为公式，支持手动修订边界后重算。');
source.getRange('A57:D57').values=[['x 坐标 (px)','上缘 y (px)','可见下缘 y (px)','中心 y (px)']];
header(source,'A57:D57');
source.getRange('A58:C290').values=data.edges.map(edge=>edge.slice(0,3));
put(source,'D58','=(B58+C58)/2');
source.getRange('D58:D290').fillDown();
source.getRange('B58:C290').format.fill=input;
source.getRange('D58:D290').format.fill=calc;
source.getRange('D58:D290').setNumberFormat('0.0');
source.freezePanes.freezeRows(5);

const cfg=data.config;
const keep=(name,unit,status,note)=>parameter(name,cfg[name],cfg[name],unit,status,note);
parameter('W',cfg.W,"='图像测量'!B6",'px','图像确定','JPEG 原始宽度，与源码一致。');
parameter('H',cfg.H,"='图像测量'!B7",'px','图像确定','JPEG 原始高度，与源码一致。');
const extrema=(fn,col,channel)=>`${fn}(${channelRows[channel].map(row=>`'图像测量'!${col}${row}`).join(',')})`;
const lab=[0,`=MIN(100,ROUNDUP(${extrema('MAX','D','L')}+'图像测量'!B20,0))`,
 `=MAX(-128,INT(${extrema('MIN','C','A')}-'图像测量'!B21))`,
 `=MIN(127,ROUNDUP(${extrema('MAX','D','A')}+'图像测量'!B21,0))`,
 `=MAX(-128,INT(${extrema('MIN','C','B')}-'图像测量'!B21))`,
 `=MIN(127,ROUNDUP(${extrema('MAX','D','B')}+'图像测量'!B21,0))`];
['L_MIN','L_MAX','A_MIN','A_MAX','B_MIN','B_MAX'].forEach((name,i)=>{
  parameter(name,cfg.LAB_THRESHOLDS[0][i],lab[i],i<2?'L':'a/b','单图候选',
    i===0?'取合法亮度下限 0，保留更暗胶带。':'四处目标内部样本极值加余量；收窄色度须用现场多光照样本复核。');
});
keep('BLUR_KERNEL_SIZE','px','保留，待对比','本次离线采用 5×5 近似滤波；核优劣需多帧对比。');
keep('MORPH_KERNEL_SIZE','px','保留，待对比','3×3 核远小于本图约 20 px 的竖线宽度。');
keep('Mark_trigger_x_ratio','比例','保留，待标定','现中心为 x=208；本图竖线约 x=188，仍在窗口内。触发时机不能由单帧决定。');
keep('MARK_TRIGGER_HALF_WIDTH','px','保留，待动态测','现窗口为 174…242，覆盖本图竖线。需结合车速、帧率验证。');
keep('Mark_half_w','px','未使用','此变量在当前 main.py 后续未被引用，修改不会改变检测。');
keep('MARK_MIN_AREA','px²','保留，待动态测','候选竖线裁剪后包围框约 20×58；不能用大目标单帧确定最小门限。');
keep('MARK_MIN_PIXELS','px','保留，待动态测','候选掩膜竖线约 1132 前景像素，仅为离线近似。');
keep('MARK_MIN_HEIGHT','px','保留，待动态测','候选竖线裁剪后约 58 px，本图满足 14 px 门限。');
keep('MARK_MAX_WIDTH','px','保留，待动态测','本图竖线约 20 px，28 px 留有约 8 px 宽度余量。');
keep('MARK_MIN_ASPECT_RATIO','h/w','保留，待动态测','候选裁剪后 h/w≈2.9，大于现值 1.8。');
parameter('MAX_JUNCTION_GAP',cfg.MAX_JUNCTION_GAP,"=C33+'图像测量'!B19",'px','联动试验初值','与 V_TO_LINE_GAP 一起调整：裁剪距离加 4 px 余量，避免裁得越多反而拒绝交点。');
keep('JUNCTION_CONFIRM_FRAMES','帧','需视频实测','保留 3。需有效 FPS、车速、窗口停留时间及误检记录。');
keep('JUNCTION_RELEASE_FRAMES','帧','需视频实测','保留 5。需相邻地标间隔及窗口清空帧数，单图不能计算。');
keep('M_ROI_X_RATIO','比例','本图覆盖，保留','主 ROI 左界 16；图中目标横跨该区域。');
keep('M_ROI_Y_RATIO','比例','本图覆盖，保留','保留画面顶部的竖线可见部分。');
keep('M_ROI_W_RATIO','比例','本图覆盖，保留','主 ROI 宽 288，右边界 304（不含）。');
keep('M_ROI_H_RATIO','比例','本图覆盖，保留','主 ROI 高 132，本图主要车体位于其下方；极限姿态待测。');
keep('H_ROI_Y_RATIO','比例','本图覆盖，保留','相对主 ROI 高度：int(132×0.48)=63，不是相对全图高度。');
keep('H_ROI_H_RATIO','比例','本图覆盖，保留','int(132×0.35)=46，检测行 63…108 覆盖当前横线。');
keep('MIN_V_ROI_HEIGHT','px','保留，待动态测','最小 ROI 高度，与 MARK_MIN_HEIGHT 的色块高度意义不同。');
parameter('V_TO_LINE_GAP',cfg.V_TO_LINE_GAP,
 "=ROUNDUP(('图像测量'!B12-'图像测量'!B11+1)/2+'图像测量'!B18,0)",
 'px','联动试验初值','可见横线厚约 14 px；半厚 7 加 5 px 余量得到 12，减少横线与竖线粘连。');
keep('L_min_area','px²','保留，待动态测','当前 H ROI 近似掩膜约 3464 前景像素；不能据单帧确定最小面积。');
keep('L_min_pixels','px','保留，待动态测','图中前景充分，现门限 80 本身不显得过高；line:lost 根因尚未确定。');
keep('L_min_length','px','保留，待动态测','实际检查 abs(dx)≥60；本图横线在主 ROI 内贯穿约 288 px。');
keep('MAX_H_slope','dy/dx','保留，待转弯测','0.45 约对应 ±24.2°；本图近水平不能确定最大容许斜率。');
parameter('BINARY_WHITE_MIN',200,200,'灰度','保持','针对二值掩膜白色前景，不是胶带原图 LAB 阈值。');
parameter('BINARY_WHITE_MAX',255,255,'灰度','保持','与 BINARY_WHITE_MIN 合成 [[200,255]]。');
parameter('Target_Y',cfg.Target_Y,
 `=IF('图像测量'!B22="是",ROUND('图像测量'!B8*INT(${p('W')}*${p('Mark_trigger_x_ratio')})+'图像测量'!B9,1),B44)`,
 'px','有条件标定','照片为理想姿态时可取约 74.6；未确认则保留 82。测量误差约 ±2 px，需板端重新标零。');
keep('HEADING_SAMPLE_HALF_WIDTH','px','保持','当前两个采样点 x=148、268 均处于有效横线范围内。');
// Resolve references after the register exists, avoiding row-number assumptions.
put(params,`C${parameterRows.get('MAX_JUNCTION_GAP')}`,`=${p('V_TO_LINE_GAP')}+'图像测量'!B19`);
put(params,`C${parameterRows.get('Target_Y')}`,
 `=IF('图像测量'!B22="是",ROUND('图像测量'!B8*INT(${p('W')}*${p('Mark_trigger_x_ratio')})+'图像测量'!B9,1),B${parameterRows.get('Target_Y')})`);
const lastParameter=5+parameterRows.size;
params.tables.add(`A5:E${lastParameter}`,true,'CalibrationParameters');
params.freezePanes.freezeRows(5);
params.getRange(`B6:C${lastParameter}`).setNumberFormat('0');
for(const name of ['Mark_trigger_x_ratio','MARK_MIN_ASPECT_RATIO','M_ROI_X_RATIO',
 'M_ROI_Y_RATIO','M_ROI_W_RATIO','M_ROI_H_RATIO','H_ROI_Y_RATIO','H_ROI_H_RATIO','MAX_H_slope']) {
  params.getRange(`B${parameterRows.get(name)}:C${parameterRows.get(name)}`).setNumberFormat('0.00');
}
params.getRange(`B${parameterRows.get('Target_Y')}:C${parameterRows.get('Target_Y')}`).setNumberFormat('0.0');
params.getRange('A48:E48').values=[['派生量 / 本图估计',null,'计算值','单位','类型']];
header(params,'A48:E48');
result('main_left',`=INT(${p('W')}*${p('M_ROI_X_RATIO')})`,'px','主 ROI 左界。');
result('main_top',`=INT(${p('H')}*${p('M_ROI_Y_RATIO')})`,'px','主 ROI 上界。');
result('main_width',`=INT(${p('W')}*${p('M_ROI_W_RATIO')})`,'px','主 ROI 宽。');
result('main_height',`=INT(${p('H')}*${p('M_ROI_H_RATIO')})`,'px','主 ROI 高。');
result('H_roi_y',`=${r('main_top')}+INT(${r('main_height')}*${p('H_ROI_Y_RATIO')})`,'px','横线 ROI 顶部。');
result('H_roi_height',`=INT(${r('main_height')}*${p('H_ROI_H_RATIO')})`,'px','横线 ROI 高。');
result('mark_trigger_x',`=INT(${p('W')}*${p('Mark_trigger_x_ratio')})`,'px','当前触发中心，不自动对准单张照片中的竖线。');
result('sample_x_left',`=MAX(${r('main_left')},${r('mark_trigger_x')}-${p('HEADING_SAMPLE_HALF_WIDTH')})`,'px','左侧方向采样点。');
result('sample_x_right',`=MIN(${r('main_left')}+${r('main_width')}-1,${r('mark_trigger_x')}+${p('HEADING_SAMPLE_HALF_WIDTH')})`,'px','右侧方向采样点。');
result('本图 y(trigger)',`='图像测量'!B8*${r('mark_trigger_x')}+'图像测量'!B9`,'px','边界中心拟合结果约 74.6±2；不代表设备已经识别到横线。');
result('position_error_px',`=${r('本图 y(trigger)')}-${p('Target_Y')}`,'px','本图几何代入源码定义；截图实际显示 invalid，未输出有效误差。');
result('heading_error_px',`='图像测量'!B8*(${r('sample_x_right')}-${r('sample_x_left')})`,'px','约 0.1 px，低于边缘测量误差，实用上可视为近水平。');
result('line_angle_deg',"=DEGREES(ATAN('图像测量'!B8))",'度','约 0.1°；单张低分辨率叠加图不支持精确角度标定。');
result('可见横线厚度',"='图像测量'!B12-'图像测量'!B11+1",'px','可见厚度约 14 px，下缘受叠加线影响。');
result('竖线可见宽度',"='图像测量'!B15-'图像测量'!B14+1",'px','左右边界均包含，约 20 px。');
result('竖线可见中心',"=('图像测量'!B14+'图像测量'!B15)/2",'px','外接框几何中心约 188.5；与像素质心不同。');
result('竖线可见高度',"='图像测量'!B17-'图像测量'!B16+1",'px','约 68 px，顶部超出画面，不能推断完整地标长度。');
result('触发中心距离',`=ABS(${r('竖线可见中心')}-${r('mark_trigger_x')})`,'px','约 19.5 px，小于当前半窗宽 34。');
result('触发窗口覆盖',`=IF(${r('触发中心距离')}<=${p('MARK_TRIGGER_HALF_WIDTH')},"覆盖","不覆盖")`,'','仅验证本帧位置条件。');
result('竖线处裁剪 y',`=MAX(${r('main_top')},MIN(INT('图像测量'!B8*${r('竖线可见中心')}+'图像测量'!B9)-${p('V_TO_LINE_GAP')},${r('main_top')}+${r('main_height')}))`,'px','从此行起清零；候选参数得到 y=62，最后保留行 y=61。');
result('联动间距余量',`=${p('MAX_JUNCTION_GAP')}-${p('V_TO_LINE_GAP')}`,'px','须留出取整、分割边缘及波动余量；建议 4 px，待实测。');
result('LAB_THRESHOLDS',`="[["&${p('L_MIN')}&","&${p('L_MAX')}&","&${p('A_MIN')}&","&${p('A_MAX')}&","&${p('B_MIN')}&","&${p('B_MAX')}&"]]"`,'','供复制的候选列表；建议保留旧阈值作为对照。');
params.getRange('C49:C69').setNumberFormat('0.0##');
params.getRange('C49:C57').setNumberFormat('0');
params.getRange('C58:C66').setNumberFormat('0.0');
params.getRange('C68:C69').setNumberFormat('0');
params.getRange('C70').format.columnWidthPx=120;
params.getRange('C70:E70').format.rowHeight=38;
params.getRange('C70').format.wrapText=true;

put(params,'A73','离线近似对照（固定截图统计，更改参数不会重新分割图像）');
params.getRange('A75:E75').values=[['阈值方案 / 裁剪间隔','色块宽 px','色块高 px','像素数','最大宽度门限对照']];
header(params,'A75:E75');
[['current','3'],['current','12'],['candidate','3'],['candidate','12']].forEach(([name,gap],index)=>{
  const row=76+index, blob=data.simulations[name].gaps[gap][0];
  params.getRange(`A${row}:E${row}`).values=[[`${name==='current'?'原 LAB':'候选 LAB'}，gap=${gap}`,blob.w,blob.h,blob.pixels,null]];
  put(params,`E${row}`,`=IF(B${row}<=${p('MARK_MAX_WIDTH')},"宽度通过","宽度不通过")`);
});
put(params,'G76','gap=3 时主要前景与横线残留粘连，宽约 285 px，超过 MARK_MAX_WIDTH=28。');
put(params,'G77','gap=12 后原 LAB 得到约 20×59 px 的独立竖线，本图无需先更换 LAB 才能分离。');
put(params,'G78','候选 LAB 收窄了色度范围，仍不能代替裁剪间隔调整。');
put(params,'G79','候选 LAB 加 gap=12 得到约 20×58 px、1132 像素；不是板端实测。');
params.getRange('G76:G79').format.wrapText=true;
params.getRange('A76:H79').format.rowHeight=36;
put(params,'A82','现场待测：有效 FPS、像素移动速度、相邻地标清空时间、正常/反光/阴影原始帧。');
put(params,'A83','截图 line:lost 不能由此表确诊。应先检查板端 LAB 掩膜、回归候选、运行版本与部署源码是否一致。');
put(params,'A84','数值未写回 main.py。先对比二值图，再验证裁剪后竖线，最后测试多帧计数。');
put(params,'A85','串口引脚、波特率和计数历史无法从照片计算；本表仅覆盖视觉参数区。');
params.getRange('E76:E79').conditionalFormats.add('containsText',{
 text:'不通过',format:{fill:'#FCE4D6',font:{color:'#9C2323'}}});
source.getRange('A57:D57').format.wrapText=true;
source.getRange('A57:D57').format.rowHeight=38;
source.getRange('A29:H29').format.wrapText=true;
source.getRange('A29:H29').format.rowHeight=38;

// Exercise the ideal-pose control and restore it before the final recalculation.
put(source,'B22','是');
wb.recalculate();
const zero=params.getRange(`C${parameterRows.get('Target_Y')}`).values[0][0];
if(Math.abs(zero-74.6)>0.01) throw new Error(`Target_Y recalculation failed: ${zero}`);
put(source,'B22','未确认');
wb.recalculate();
const expected={mark_trigger_x:208,'本图 y(trigger)':74.63419808265317,
 position_error_px:-7.365801917346833,'竖线处裁剪 y':62};
for(const [name,value] of Object.entries(expected)) {
  const actual=params.getRange(`C${resultRows.get(name)}`).values[0][0];
  if(Math.abs(actual-value)>1e-6) throw new Error(`${name}: ${actual} != ${value}`);
}
for(const [name,value] of [['V_TO_LINE_GAP',12],['MAX_JUNCTION_GAP',16],['Target_Y',82]]) {
  if(params.getRange(`C${parameterRows.get(name)}`).values[0][0]!==value) throw new Error(name);
}
console.log((await wb.inspect({kind:'table',range:'参数标定!A58:E70',include:'values,formulas',
 tableMaxRows:13,tableMaxCols:5,maxChars:3500})).ndjson);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!',
 options:{useRegex:true,maxResults:30},summary:'formula errors'})).ndjson);
for(const [sheetName,range,file] of [['参数标定','A2:H21','parameters.png'],
 ['参数标定','A22:H42','parameters_rest.png'],['图像测量','A2:H27','measurements.png'],
 ['图像测量','A29:H59','samples.png'],['参数标定','A48:H79','calculations.png']]) {
  const preview=await wb.render({sheetName,range,scale:1,format:'png'});
  await fs.writeFile(path.join(out,file),new Uint8Array(await preview.arrayBuffer()));
}
await (await SpreadsheetFile.exportXlsx(wb)).save(path.join(out,'main_图像参数标定.xlsx'));
console.log(JSON.stringify({parameterCount:parameterRows.size,parameterRows:Object.fromEntries(parameterRows),
 output:path.join(out,'main_图像参数标定.xlsx'),checks:'passed'},null,2));
