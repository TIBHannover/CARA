# Glossary

The words CARA uses for relevance assessment of image retrieval results, in the app, the code and these docs.

## Data

**Dataset**:
A collection of images with one or more query sets, and optionally their embeddings. Several studies can share one.

**Query set**:
A named set of queries in a dataset, all of one kind: image, text, or image + text (composed).

**Corpus**:
The images of a dataset that queries retrieve from.

**Pool**:
The images judged for one query, drawn by candidate sampling.

**Candidate sampling**:
How a study draws each query's pool: its given candidates, the nearest neighbours of one or more encoders, or a
random sample.

**Encoder**:
The model whose embeddings group a study's images and, for nearest neighbours, sample its pools.

## Studies

**Study**:
The judging of one query set (all of it or a sample) with its own settings and people.

**Pilot**:
A few queries of a study, judged one image at a time before the grouping is chosen.

**Annotation**:
The phase of a study after the pilot, in which annotators judge the other queries in groups.

**Stage**:
Where a study is: not started, pilot, annotation or done.

**Admin**:
A person who manages a study; admins don't judge.

**Annotator**:
A person who judges a study's queries; the IR literature also says assessor.

**Adjudicator**:
A person who sets the final labels where annotators disagree or are unsure; adjudicators don't judge.

**Guidelines**:
What annotators read before and while judging: the admin's text, with examples placed in it, usually picked
from images the pilot annotators disagreed on.

## Judging

**Label**:
One of a study's answers to "is this image relevant to the query?", such as Relevant, Not Relevant or Unsure.

**Grade**:
The relevance a label stands for in the qrels; a label without a grade (such as Unsure) is left out of them.

**Judgment**:
One annotator's label for one image of one pool.

**Group**:
Images of a pool similar enough to be labelled with one click.

**Ungrouped**:
The images of a pool judged on their own: those unlike any other, and, if the admin set it, those most similar
to the query.

**Split**:
Dividing a mixed group in two.

**Suggestion**:
A label proposed for an unjudged image because it is clearly similar to images an annotator has labelled.

**Review**:
A second look at a labelled pool, sorted by label.

**Consensus**:
The label most annotators gave an image; a tie leaves it undecided.

**Adjudication**:
Setting an image's final label, by an adjudicator or an admin.

**Final label**:
The label an adjudicator or admin sets for an image; it overrides the consensus.

## Simulation

**Grouping setting**:
A grouping method with its values, and the rules for which images stay ungrouped. The simulator compares these;
*setting* on its own means a grouping setting on the simulation pages.

**Study settings**:
Everything a study is configured with, such as its pools, labels, review round and grouping setting.

**Simulated annotator**:
A model of an annotator: how often it errs, how closely it looks at large groups, how long each action takes.

**Annotator type**:
A named simulated annotator, such as Typical, or one measured from a pilot annotator.
