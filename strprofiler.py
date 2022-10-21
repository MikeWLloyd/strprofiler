import pandas as pd
import rich_click as click
from pathlib import Path
from datetime import datetime
import numpy as np
from collections import OrderedDict
from math import nan
import sys


def str_ingress(
    paths, sample_col="Sample", marker_col="Marker", sample_map=None, penta_fix=True
):
    """Reads in a list of paths and returns a pandas DataFrame of STR alleles in long format.

    :param paths: STR profile files to read in.
    :type paths: list of pathlib.Path
    :param sample_col: Name of sample column in each STR profile, defaults to "Sample"
    :type sample_col: str, optional
    :param marker_col: Name of marker identifier column in each STR profile,
        defaults to "Marker". Ignored if file in long format.
    :type marker_col: str, optional
    :param sample_map: Two column DataFrame containing sample identifiers in first column
        and new sample names to apply in second column, defaults to None
    :type sample_map: pandas.DataFrame, optional
    :param penta_fix: Whether to try to coerce "Penta" alleles to a common spelling, defaults to True
    :type penta_fix: bool, optional
    :return: A pandas DataFrame of STR alleles in long format.
    :rtype: pandas.DataFrame
    """

    samps_dicts = []

    for path in paths:
        path = Path(path)
        if path.suffix == ".xlsx":
            df = pd.read_excel(path)
        elif path.suffix == ".csv":
            df = pd.read_csv(path)
        elif path.suffix == ".tsv":
            df = pd.read_csv(path, sep="\t")
        elif path.suffix == ".txt":
            df = pd.read_csv(path, sep="\t")

        df = df.applymap(lambda x: x.strip() if type(x) == str else x)

        df.columns = df.columns.str.strip()

        # Collapse allele columns for each marker into a single column if in wide format.
        # ".0" strip handles edgecase where some alleles have a trailing ".0".
        if len(df.filter(like="Allele").columns) > 0:
            df["Alleles"] = (
                df.filter(like="Allele")
                .apply(
                    lambda x: ",".join(
                        [str(y).strip().rstrip(".0") for y in x if str(y) != "nan"]
                    ),
                    axis=1,
                )
                .str.strip(",")
            )

            # Group and collect dict from each sample for markers and alleles.
            grouped = df.groupby(sample_col)

            for samp in grouped.groups.keys():
                samp_df = grouped.get_group(samp)
                samps_dict = samp_df.set_index(marker_col).to_dict()["Alleles"]
                samps_dict["Sample"] = samp

                # Remove duplicate alleles.
                for k in samps_dict.keys():
                    if k != "Sample":
                        samps_dict[k] = ",".join(
                            OrderedDict.fromkeys(samps_dict[k].split(","))
                        )

                # Rename PentaD and PentaE from common spellings.
                if penta_fix:
                    if "Penta D" in samps_dict.keys():
                        samps_dict["PentaD"] = samps_dict.pop("Penta D")
                    elif "Penta_D" in samps_dict.keys():
                        samps_dict["PentaD"] = samps_dict.pop("Penta_D")

                    if "Penta E" in samps_dict.keys():
                        samps_dict["PentaE"] = samps_dict.pop("Penta E")
                    elif "Penta_E" in samps_dict.keys():
                        samps_dict["PentaE"] = samps_dict.pop("Penta_E")

                samps_dicts.append(samps_dict)
        # If in long format, just collect dict from each sample for markers and alleles.
        else:
            df = df.replace(np.nan, "")
            df = df.astype(str)
            samps_list = df.to_dict("records")
            for s in samps_list:
                s["Sample"] = s.pop(sample_col)

                # Remove duplicate alleles, trim trailing ".0".
                for k in s.keys():
                    if k != "Sample":
                        s[k] = _clean_element(s[k])

                samps_dicts.append(s)

    allele_df = pd.DataFrame(samps_dicts)

    # Replace sample names with sample map if provided.
    if sample_map is not None:
        for id in sample_map.iloc[:, 0]:
            allele_df.loc[allele_df["Sample"] == id, "Sample"] = sample_map.iloc[:, 1][
                sample_map.iloc[:, 0] == id
            ].to_string(header=False, index=False)

    # Set index to sample name.
    allele_df.set_index("Sample", inplace=True, verify_integrity=True)

    # Remove Nans.
    allele_df = allele_df.replace({np.nan: ""})

    return allele_df


def _clean_element(x):
    """Takes a string of alleles, removes duplicates, trims trailing .0, and returns a cleaned string."""
    elements = [s.strip().rstrip(".0") for s in x.split(",")]
    # Remove duplicates.
    elements = list(set(elements))
    elements.sort()
    return ",".join(elements)


def score_query(query, reference, use_amel=False, amel_col="AMEL"):
    """Calculates the Tanabe and Masters scores for a query sample against a reference sample.

    :param query: Alleles for query sample.
    :type query: dict
    :param reference: Alleles for reference sample.
    :type reference: dict
    :param use_amel: Whether to include amelogenin in scoring, defaults to False
    :type use_amel: bool, optional
    :param amel_col: Name of amelogenin column, defaults to "AMEL"
    :type amel_col: str, optional
    :return: Dictionary of scores for query sample against reference sample.
    :rtype: dict
    """

    n_r_alleles = 0
    n_q_alleles = 0

    n_shared_alleles = 0

    # Convert allele values to lists, removing markers with no alleles, and uniquifying alleles.
    query = {k: list(set(v.split(","))) for k, v in query.items() if v != ""}
    reference = {k: list(set(v.split(","))) for k, v in reference.items() if v != ""}

    # Get unique markers in query and reference.
    markers = list(set(query.keys()) & set(reference.keys()))

    # Remove amelogenin markers if use_amel is False.
    if use_amel is False:
        if amel_col in markers:
            markers.remove(amel_col)

    # Calculate the number of shared markers.
    n_shared_markers = len(markers)

    # Calculate the number of shared alleles.
    for m in markers:
        n_r_alleles += len(reference[m])
        n_q_alleles += len(query[m])
        n_shared_alleles += len(set(reference[m]) & set(query[m]))

    # Calculate the scores.
    tanabe_score = 100 * ((2 * n_shared_alleles) / (n_q_alleles + n_r_alleles))
    masters_q_score = 100 * (n_shared_alleles / n_q_alleles)
    masters_r_score = 100 * (n_shared_alleles / n_r_alleles)

    out = {
        "n_shared_markers": n_shared_markers,
        "query_sample": False,
        "n_shared_alleles": n_shared_alleles,
        "n_query_alleles": n_q_alleles,
        "n_reference_alleles": n_r_alleles,
        "tanabe_score": tanabe_score,
        "masters_query_score": masters_q_score,
        "masters_ref_score": masters_r_score,
    }

    return out


def mixing_check(alleles, three_allele_threshold=3):
    """Checks for potential sample mixing.

    :param alleles: Alleles for sample.
    :type alleles: dict
    :param three_allele_threshold: Number of markers with >2 alleles allowed before
        sample is flagged for potential mixing, defaults to 3
    :type three_allele_threshold: int, optional
    :return: Whether sample is potentially mixed.
    :rtype: bool
    """

    mixed = False
    past_th = 0

    for a in alleles.keys():
        all_a = alleles[a].split(",")
        if len(all_a) > 2:
            past_th += 1

    if past_th > three_allele_threshold:
        mixed = True

    return mixed


def make_summary(
    samp_df, alleles, tan_threshold, mas_q_threshold, mas_r_threshold, mixed, s_name
):
    """Generate summary line from full sample-specific output.

    :param samp_df: Sample-specific output DataFrame containing all comparisons to other samples.
    :type samp_df: pandas.DataFrame
    :param alleles: Alleles for sample.
    :type alleles: dict
    :param tan_threshold: Tanabe score threshold to report matching samples.
    :type tan_threshold: float
    :param mas_q_threshold: Masters (query) score threshold to report matching samples.
    :type mas_q_threshold: float
    :param mas_r_threshold: Masters (reference) score threshold to report matching samples.
    :type mas_r_threshold: float
    :param mixed: Flag for whether sample is potentially mixed.
    :type mixed: bool
    :param s_name: Sample name.
    :type s_name: str
    :return: Dictonary of summary line output for sample.
    :rtype: OrderedDict
    """

    tanabe_match = samp_df[samp_df["tanabe_score"] >= tan_threshold]
    tanabe_out = (
        tanabe_match["Sample"]
        + ": "
        + tanabe_match["tanabe_score"].round(decimals=2).astype(str)
    )
    tanabe_out = tanabe_out.tolist()
    tanabe_out = "; ".join(tanabe_out)

    # Get the top hits.
    top_hit = (
        samp_df["Sample"].iloc[1]
        + ": "
        + samp_df["tanabe_score"].round(decimals=2).astype(str).iloc[1]
    )
    next_hit = (
        samp_df["Sample"].iloc[2]
        + ": "
        + samp_df["tanabe_score"].round(decimals=2).astype(str).iloc[2]
    )

    masters_q_match = samp_df[samp_df["masters_query_score"] >= mas_q_threshold]
    masters_q_out = (
        masters_q_match["Sample"]
        + ": "
        + masters_q_match["masters_query_score"].round(decimals=2).astype(str)
    )
    masters_q_out = masters_q_out.tolist()
    masters_q_out = "; ".join(masters_q_out)

    masters_r_match = samp_df[samp_df["masters_ref_score"] >= mas_r_threshold]
    masters_r_out = (
        masters_r_match["Sample"]
        + ": "
        + masters_r_match["masters_ref_score"].round(decimals=2).astype(str)
    )
    masters_r_out = masters_r_out.tolist()
    masters_r_out = "; ".join(masters_r_out)

    summ_out = OrderedDict(
        {
            "Sample": s_name,
            "mixed": mixed,
            "top_hit": top_hit,
            "next_best": next_hit,
            "tanabe_matches": tanabe_out,
            "masters_query_matches": masters_q_out,
            "masters_ref_matches": masters_r_out,
        }
    )
    summ_out.update(alleles)

    return summ_out


@click.command()
@click.option(
    "-tanth",
    "--tan_threshold",
    default=80,
    help="Minimum Tanabe score to report as potential matches in summary table.",
    show_default=True,
    type=float,
)
@click.option(
    "-masqth",
    "--mas_q_threshold",
    default=80,
    help="Minimum Masters (vs. query) score to report as potential matches in summary table.",
    show_default=True,
    type=float,
)
@click.option(
    "-masrth",
    "--mas_r_threshold",
    default=80,
    help="Minimum Masters (vs. reference) score to report as potential matches in summary table.",
    show_default=True,
    type=float,
)
@click.option(
    "-mix",
    "--mix_threshold",
    default=3,
    help="Number of markers with >= 2 alleles allowed before a sample is flagged for potential mixing.",
    show_default=True,
    type=int,
)
@click.option(
    "-sm",
    "--sample_map",
    help="""Path to sample map in csv format for renaming.
              First column should be sample names as given in STR file(s),
              second should be new names to assign. No header.""",
    type=click.Path(),
)
@click.option(
    "-acol",
    "--amel_col",
    help="Name of Amelogenin column in STR file(s).",
    default="AMEL",
    show_default=True,
    type=str,
)
@click.option(
    "-scol",
    "--sample_col",
    help="Name of sample column in STR file(s).",
    default="Sample",
    show_default=True,
    type=str,
)
@click.option(
    "-mcol",
    "--marker_col",
    help="""Name of marker column in STR file(s).
              Only used if format is 'wide'.""",
    default="Marker",
    show_default=True,
    type=str,
)
@click.option(
    "-pfix",
    "--penta_fix",
    help="""Whether to try to harmonize PentaE/D allele spelling.""",
    default=True,
    show_default=True,
    type=bool,
)
@click.option(
    "-amel",
    "--score_amel",
    help="""Use Amelogenin for similarity scoring.""",
    default=False,
    show_default=True,
    type=bool,
)
@click.option(
    "-o",
    "--output_dir",
    default="./STRprofiler",
    help="Path to the output directory.",
    show_default=True,
    type=click.Path(),
)
@click.argument("input_files", required=True, type=click.Path(exists=True), nargs=-1)
@click.version_option()
def strprofiler(
    input_files,
    sample_map=None,
    output_dir="./STRprofiler",
    tan_threshold=80,
    mas_q_threshold=80,
    mas_r_threshold=80,
    mix_threshold=4,
    amel_col="AMEL",
    sample_col="Sample Name",
    marker_col="Marker",
    penta_fix=True,
    score_amel=False,
):
    """STRprofiler compares STR profiles to each other.

    :param input_files: List of input STR files in csv, xlsx, tsv, or txt format.
    :type input_files: click.Path
    :param sample_map: Path to sample map in csv format for renaming.
        First column should be sample names as given in STR file(s),
        second should be new names to assign. No header., defaults to None
    :type sample_map: str, optional
    :param output_dir: Path to output directory, defaults to "./STRprofiler"
    :type output_dir: str, optional
    :param tan_threshold: Minimum Tanabe score to report as potential matches in summary table, defaults to 80
    :type tan_threshold: int, optional
    :param mas_q_threshold: Minimum Masters (vs. query) score to report as potential matches in summary table, defaults to 80
    :type mas_q_threshold: int, optional
    :param mas_r_threshold: Minimum Masters (vs. reference) score to report as potential matches in summary table,
        defaults to 80
    :type mas_r_threshold: int, optional
    :param mix_threshold: Number of markers with >= 2 alleles allowed before a sample is flagged for potential mixing,
        defaults to 4
    :type mix_threshold: int, optional
    :param amel_col: Name of Amelogenin column in STR file(s), defaults to "AMEL"
    :type amel_col: str, optional
    :param sample_col: Name of sample column in STR file(s), defaults to "Sample Name"
    :type sample_col: str, optional
    :param marker_col: Name of marker column in STR file(s).
        Only used if format is 'wide', defaults to "Marker"
    :type marker_col: str, optional
    :param penta_fix: Whether to try to harmonize PentaE/D allele spelling, defaults to True
    :type penta_fix: bool, optional
    :param score_amel: Use Amelogenin for similarity scoring., defaults to False
    :type score_amel: bool, optional
    """

    # Make output directory and open file for logging.
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    dt_string = now.strftime("%Y%m%d.%H_%M_%S")
    log_file = open(Path(output_dir, "strprofiler." + dt_string + ".log"), "w")

    print("Tanabe threshold: " + str(tan_threshold), file=log_file)
    print("Masters (vs. query) threshold: " + str(mas_q_threshold), file=log_file)
    print("Masters (vs. reference) threshold: " + str(mas_r_threshold), file=log_file)
    print("Mix threshold: " + str(mix_threshold), file=log_file)
    print("Sample map: " + sample_map, file=log_file)
    print("Amelogenin column: " + amel_col, file=log_file)
    print("Sample column: " + sample_col, file=log_file)
    print("Marker column: " + marker_col, file=log_file)
    print("Penta fix: " + str(penta_fix), file=log_file)
    print("Use amelogenin for scoring: " + str(score_amel) + "\n", file=log_file)
    print("Full command: ", file=log_file)
    
    print(sys.argv[0], file=log_file)

    # Check for sample map.
    if sample_map is not None:
        sample_map = pd.read_csv(sample_map, header=None, encoding="unicode_escape")

    # Data ingress.
    df = str_ingress(
        paths=input_files,
        sample_col=sample_col,
        marker_col=marker_col,
        sample_map=sample_map,
        penta_fix=penta_fix,
    )

    samps = df.to_dict(orient="index")
    summaries = []

    # Iterate through samples and compare to each other.
    for s in samps.keys():
        q = samps[s]
        # Check for sample mixing.
        mixed = mixing_check(alleles=q, three_allele_threshold=mix_threshold)

        q_out = {
            "Sample": s,
            "mixed": mixed,
            "query_sample": True,
            "n_shared_markers": nan,
            "n_shared_alleles": nan,
            "n_query_alleles": nan,
            "n_reference_alleles": nan,
            "tanabe_score": nan,
            "masters_query_score": nan,
            "masters_ref_score": nan,
        }
        q_out.update(q)

        # Put query sample first.
        samp_comps = [q_out]

        for sa in samps.keys():
            if sa != s:
                r = samps[sa]
                print("Comparing " + s + " to " + sa, file=log_file)
                scores = score_query(query=q, reference=r, use_amel=score_amel)

                # Create dict of scores for each sample comparison.
                samp_out = OrderedDict({"Sample": sa})
                samp_out.update(scores)
                samp_out.update(r)

                samp_comps.append(samp_out)

        # Create DataFrame of scores for each sample comparison.
        full_samp_out = pd.DataFrame(samp_comps)
        full_samp_out.sort_values(
            by="tanabe_score", ascending=False, inplace=True, na_position="first"
        )

        # Write sample-specific output.
        full_samp_out.to_csv(
            Path(output_dir, s + ".strprofiler." + dt_string + ".csv"), index=False
        )

        # Generate summary of scores for given sample.
        summ = make_summary(
            samp_df=full_samp_out,
            alleles=q,
            tan_threshold=tan_threshold,
            mas_q_threshold=mas_q_threshold,
            mas_r_threshold=mas_r_threshold,
            mixed=mixed,
            s_name=s,
        )

        summaries.append(summ)

    summaries = pd.DataFrame(summaries)
    # Write summary output.
    summaries.to_csv(
        Path(output_dir, "full_summary.strprofiler." + dt_string + ".csv"), index=False
    )

    log_file.close()
